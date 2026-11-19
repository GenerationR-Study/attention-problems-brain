"""
The COMPARE tab.

Two maps are chosen here, independently of the results page, and compared
either as a difference or as a cluster overlap.
"""
import numpy as np
from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui

import definitions.layout_styles as styles
from definitions import plotting as vwp
from definitions.backend_results import (
    compute_difference, compute_overlap, extract_results, is_same_mesh,
    shared_vertices,
)
from definitions.pages.common import (
    available_displays, available_resolutions, button_column,
    default_resolution, figure_outputs, figures_row, info_row,
    mark_unselectable, nav_title, resolution_ceiling, resolution_output,
    roi_choice, selection_pane, set_if_changed,
)
from definitions.pages.download import (
    DOWNLOAD_TRIGGER_JS, download_buttons, wire_download,
)
from definitions.pages.selectors import map_selector_server, map_selector_ui


def compare_page(tab_name):
    return ui.nav_panel(
        nav_title('scale-unbalanced', 'Compare maps'),
        DOWNLOAD_TRIGGER_JS,
        compare_ui('compare'),
        ' ',  # spacer
        value=tab_name)


def map_band(letter, selector_id):
    """
    One map's three dropdowns on a band of their own, with the letter that
    names it on the left -- so the dropdowns themselves can keep the same
    labels as on the results page.
    """
    return ui.div(
        ui.div(letter, style=styles.MAP_BADGE),
        # min-width: 0 so the dropdowns take what is left of the band and
        # shrink with it, instead of pushing the letter out
        ui.div(ui.layout_columns(*map_selector_ui(selector_id),
                                 col_widths=(4, 4, 4), gap='20px'),
               style='flex: 1; min-width: 0'),
        style=styles.MAP_ROW)


@module.ui
def compare_ui():
    return ui.div(
        # Selection pane: one band per map, each badged with its letter, then
        # the comparison mode and the ROI contours (surface and resolution live
        # in the brains card header)
        ui.layout_columns(
            selection_pane(
                map_band('A', 'map_a'),
                map_band('B', 'map_b'),
                # Rendered by the server: cluster overlap needs both maps to
                # have been cluster corrected
                ui.output_ui('compare_mode_ui'),
                roi_choice('select_roi'),
                col_widths=(12, 12, 2, 10),
            ),
            button_column(*download_buttons()),
            col_widths=(11, 1)
        ),
        info_row(),
        figures_row())


@module.server
def update_compare(input: Inputs, output: Outputs, session: Session,
                   all_results) -> None:

    selection_a = map_selector_server('map_a', all_results=all_results)
    selection_b = map_selector_server('map_b', all_results=all_results)

    # Split the same way as the results page: changing the surface must not
    # rebuild the legend, and must not re-read the result files.
    maps_settings = reactive.Value(None)   # (selection A, selection B, mode)
    view_settings = reactive.Value(None)   # (surface, resolution, ROI contours)

    @reactive.Calc
    def selected_roi():
        return tuple(input.select_roi())

    @reactive.Effect
    @reactive.event(input.update_button, ignore_none=True)
    def snapshot_settings():
        set_if_changed(maps_settings, (selection_a(), selection_b(),
                                       input.compare_mode()))
        set_if_changed(view_settings, (input.select_surface(),
                                       input.select_resolution(),
                                       selected_roi()))

    @render.ui
    def compare_mode_ui():
        overlap_ok = all(
            'clusters' in available_displays(all_results(), model, meas)
            for model, _term, meas in (selection_a(), selection_b()))

        return mark_unselectable(
            ui.input_selectize(id='compare_mode', label='Comparison',
                               choices=styles.COMPARE_MODES,
                               selected='difference', width='100%'),
            set() if overlap_ok else {'overlap'})

    @render.ui
    def resolution_ui():
        # The coarser of the two maps is the ceiling: neither can be drawn on
        # a mesh finer than itself
        available = available_resolutions(resolution_ceiling(
            all_results(), selection_a()[0], selection_b()[0]))

        return resolution_output('select_resolution', available,
                                 default_resolution(available))

    @reactive.Calc
    def both_results():
        (model_a, term_a, meas_a), (model_b, term_b, meas_b), mode = req(maps_settings())

        with ui.Progress(min=0, max=2) as p:
            p.set(0, message='Loading the first map...')
            result_a = _read(model_a, term_a, meas_a, mode)

            p.set(1, message='Loading the second map...')
            result_b = _read(model_b, term_b, meas_b, mode)

        return mode, result_a, result_b

    def _read(which_model, which_term, which_meas, mode):
        """
        Read one of the two maps.

        Overlap needs the clusters themselves. A difference only needs the
        betas, so it is taken unthresholded, which is what lets a model that
        was never cluster corrected be compared at all.
        """
        if mode == 'overlap':
            return extract_results(all_results(), which_model, which_term,
                                   which_meas)

        return extract_results(all_results(), which_model, which_term,
                               which_meas, mask_source=None)

    @reactive.Calc
    def compare_args():
        """What to draw, in the same shape display_args() returns."""
        mode, result_a, result_b = both_results()

        if mode == 'difference':
            difference = compute_difference(result_a, result_b)

            # No mask: the difference is shown at every vertex, so the colour
            # scale spans the whole cortex rather than the clusters alone.
            return dict(lh=difference['left'], rh=difference['right'],
                        lh_mask=None, rh_mask=None,
                        cmap=None, discrete=None,
                        label='β difference (A − B)',
                        mode=vwp.DENSITY, tick_text=None)

        info, maps = compute_overlap(result_a, result_b)

        # Codes are 1 = A only, 2 = B only, 3 = both, matching OVLP_COLORS
        return dict(lh=maps['left'].astype(float), rh=maps['right'].astype(float),
                    lh_mask=maps['left'] > 0, rh_mask=maps['right'] > 0,
                    cmap=styles.OVLP_COLORS, discrete=True,
                    label='Cluster overlap',
                    mode=vwp.COLORBAR, tick_text=styles.OVERLAP_TICK_LABELS,
                    overlap_info=info)

    def _mesh_warning(result_a, result_b):
        """
        Say so when the two maps were not fitted on the same mesh.

        The comparison still runs -- the finer map is cut down to the coarser
        one's vertices, which line up because the fsaverage meshes nest -- but
        it is only ever about the part they share, and that has to be said.
        """
        if is_same_mesh(result_a, result_b):
            return ''

        sizes = {name: sum(len(result.betas[hemi]) for hemi in ('left', 'right'))
                 for name, result in (('A', result_a), ('B', result_b))}
        shared = sum(shared_vertices(result_a, result_b).values())

        return (f'</br>⚠️ **A** has <ins>{sizes["A"]:,}</ins> vertices but '
                f'**B** has <ins>{sizes["B"]:,}</ins>: only the '
                f'<ins>{shared:,}</ins> they share are compared.')

    @render.text
    def info():
        mode, result_a, result_b = both_results()
        (model_a, _, meas_a), (model_b, _, meas_b), _ = maps_settings()

        mesh_warning = _mesh_warning(result_a, result_b)

        if mode == 'difference':
            difference = compute_difference(result_a, result_b)
            both = np.concatenate([difference[h] for h in ('left', 'right')])

            warning = ''
            if meas_a != meas_b:
                # Subtracting different measures is not meaningful, but the
                # overlap of their clusters still is -- so only warn here.
                warning = (f'</br>⚠️ **A** is <ins>{styles.measure_names[meas_a]}</ins> '
                           f'but **B** is <ins>{styles.measure_names[meas_b]}</ins>: '
                           'their difference is not interpretable.')

            return ui.markdown(
                f'**{model_a}** − **{model_b}**</br>'
                f'Mean difference [range] = **{np.nanmean(both):.2f}** '
                f'[{np.nanmin(both):.2f}; {np.nanmax(both):.2f}]'
                f'{warning}{mesh_warning}')

        ovlp_info = compare_args()['overlap_info']

        text, legend = {}, {}
        for key in [1, 2, 3]:
            text[key] = (f'**{ovlp_info[key][1]}%** ({ovlp_info[key][0]} vertices)'
                         if key in ovlp_info else '**0%** (0 vertices)')
            color = styles.OVLP_COLORS[key - 1]
            legend[key] = f'<span style = "background-color: {color}; color: {color}"> oo</span>'

        return ui.markdown(
            f'There was a {text[3]} {legend[3]} **overlap** between the maps selected:</br>'
            f'{text[1]} was unique to {legend[1]} **A** — {model_a} (<ins>{meas_a}</ins>)</br>'
            f'{text[2]} was unique to {legend[2]} **B** — {model_b} (<ins>{meas_b}</ins>)'
            f'{mesh_warning}')

    @reactive.Calc
    def figure_title():
        """The title the downloaded figure carries: both maps, and the mode."""
        (model_a, _, meas_a), (model_b, _, meas_b), mode = req(maps_settings())

        if mode == 'difference':
            return f'{model_a} ({meas_a}) − {model_b} ({meas_b})'

        return f'Cluster overlap: {model_a} ({meas_a}) vs {model_b} ({meas_b})'

    figure_outputs(compare_args, view_settings)

    wire_download(input, output, session, compare_args, view_settings,
                  figure_title)
