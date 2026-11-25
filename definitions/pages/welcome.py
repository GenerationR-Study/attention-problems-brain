"""
The first tab, in either of its two forms.

Without a configured results folder it asks for one: point the app at a folder 
and hit GO. With one (see wizard_config.toml) it instead introduces the wizard 
-- its own title and description, above a summary of the results the app already 
holds.
"""
from shiny import reactive, render, ui

import pandas as pd
from great_tables import GT, loc, style

import definitions.layout_styles as styles
from definitions.backend_results import has_groups, model_summaries
from definitions.config import CONFIG
from definitions.pages.common import nav_title

FUNDING = ('This work was supported by the **FLAG-ERA** grant '
           '[*Infant2Adult*](https://www.infant2adult.com/home) '
           'and by The Netherlands Organization for Health Research and '
           'Development (**ZonMw**, grant number 16080606).')


def funding_row():
    return ui.layout_columns(
        ui.output_image('funders_image'),
        ui.markdown(FUNDING),
        col_widths=(3, 8, -1))


def welcome_page(start_folder, tab_name):
    """The WELCOME page, or the ABOUT page where results are configured."""
    if CONFIG.preset:
        return about_page(tab_name)

    return ui.nav_panel(
            nav_title('house', 'Welcome'),
            ui.markdown('</br>Welcome to the **verywise WIZARD** app!</br></br>'
                        'Here you can visualize the statistical brain surface maps obtained from your [`verywise`](https://seredef.github.io/verywise/) '
                        '(or `QDECR`) analysis in an interactive way.</br>'
                        'To start, please point us to the location of your project results. '
                        'This can be:</br>'
                        '&emsp;⇢ *A path to the results folder*</br>'
                        '&emsp;&emsp;[this is the fastest option, especially if you ran a multiple / larger models, '
                        'but it only works when using the application "offline" (see [instructions](https://github.com/SereDef/verywise-wizard#running-the-application-locally)) ]</br>'
                        '&emsp;⇢ *A directory inside a (public) github repository*</br>'
                        '&emsp;&emsp;[this is most flexible but it requires loading all '
                        'results before getting started, which may take up to a few minutes]</br></br>'
                        'Hit **GO** to see an overview of the results in the selected folder.</br>'),
            ui.input_radio_buttons(id='analysis_software', label='Analyses ran using:',
                                   choices={'QDECR': ui.markdown('`QDECR`'),
                                            'verywise': ui.markdown('`verywise`')},
                                   inline=True, selected='verywise'),
            ui.div(ui.layout_columns(
                 ui.input_text(id='results_folder', label='', value=start_folder),
                 ui.input_action_button(id='go_button',
                                        label='GO',
                                        style=f'color: white; font-weight: bold; '
                                              f'background-color: {styles.VW_COLOR_PALETTE["dark-red"]}; '
                                              f'border-color: {styles.VW_COLOR_PALETTE["dark-red"]}; '
                                              f'padding-top: 6px; padding-bottom: 6px;'),

                 col_widths=(10, 1, -1)
            )),
            ' ',  # spacer
            ui.output_ui(id='input_folder_info'),
            ui.markdown('Have fun!</br></br></br></br>'),
            funding_row(),
            value=tab_name)


DEFAULT_INTRO = (
    'The brain surface maps in this wizard were produced with '
    '[`verywise`](https://seredef.github.io/verywise/). '
    'Head to the **"Main results"** tab to look at a single map, or to '
    '**"Compare"** to put two of them side by side.')


def about_page(tab_name):
    """
    The welcome page of a configured wizard: whose results these are, and what
    is in them. No folder box and no GO button -- they are already loaded.
    """
    return ui.nav_panel(
        nav_title('house', 'Welcome'),
        # ui.h2, not markdown: a '##' that follows anything on its line (the
        # spacer this used to carry) is printed literally instead of a heading
        ui.h2(CONFIG.title, style='padding-top: 20px'),
        ui.markdown(CONFIG.intro or DEFAULT_INTRO),
        ' ',  # spacer
        ui.output_ui(id='input_folder_info'),
        funding_row(),
        value=tab_name)


def welcome_info_output(input, all_results):
    """
    Register the summary of the results folder.

    In preset mode it renders as soon as the page loads; otherwise it waits for
    GO, so that typing in the folder box does not keep rebuilding it.
    """
    if CONFIG.preset:
        @render.ui
        def input_folder_info():
            return describe_input_folder(model_dict=all_results())

        return

    @render.ui
    @reactive.event(input.go_button)
    def input_folder_info():
        return describe_input_folder(model_dict=all_results())


# ------------------------------------------------------------------------------
# Describing a model that verywise summarised for us
# ------------------------------------------------------------------------------
# Everything here reads <hemi>.<measure>.model.summary.yml. The numbers that
# guide a choice -- how many clusters each term produced -- are laid out as a
# table; the rest of the fit is folded away under it.

NO_CLUSTERS = '·'  # easier to skip over than a column of zeros


def _fmt(value, digits=0):
    """
    Thousands separators, to the requested number of decimals.

    Floats are formatted explicitly even at zero decimals, or an AIC of
    -58154.082 would print all of itself and a count of 0.0 would print '0.0'.
    """
    if value is None:
        return '--'
    if isinstance(value, float):
        return f'{value:,.{digits}f}'
    return f'{value:,}'


def _file_label(meas, hemi):
    """('thickness', 'lh') -> 'thickness L'"""
    return f'{meas} {hemi[0].upper()}'


def _scale_line(summary):
    """How big the mesh was, and how many observations went into it."""
    # Only what every map in this model shares: n_vertices_effective differs
    # per measure and hemisphere, so one of them cannot speak for the rest.
    # <b>, not markdown's '**': this block is handed over as HTML
    return (f'<b>{_fmt(summary.get("n_vertices"))}</b> vertices · '
            f'<b>{_fmt(summary.get("n_observations"))}</b> observations')


def _measure_columns(keys):
    """[(measure, [hemispheres])], in the order the columns are drawn."""
    columns = {}
    for meas, hemi in keys:
        columns.setdefault(meas, []).append(hemi)

    return list(columns.items())


def _column_id(meas, hemi):
    """One column per map: 'area' + 'lh' -> 'area_lh'."""
    return f'{meas}_{hemi}'


def _gt_html(frame, title, keys, as_html=False, bold_stub=False):
    """
    Render one of the summary tables with great-tables.

    The measures become spanners, each keeping the colour it has everywhere
    else in the app, and the hemispheres sit under them.

    `as_html` marks cells that carry markup of their own: great-tables escapes
    body cells, and going through fmt_markdown is what lets the coverage bars
    render instead of being printed as tags.
    """
    columns = [_column_id(meas, hemi)
               for meas, hemis in _measure_columns(keys) for hemi in hemis]

    table = (GT(frame, rowname_col='label')
             .tab_header(title=title)
             .cols_align(align='right'))

    if as_html:
        table = table.fmt_markdown(columns=columns)

    if bold_stub:
        table = table.tab_style(style=style.text(weight='bold'),
                                locations=loc.stub())

    for meas, hemis in _measure_columns(keys):
        table = table.tab_spanner(
            label=meas, id=meas,
            columns=[_column_id(meas, hemi) for hemi in hemis])

        table = table.tab_style(
            style=style.fill(color=styles.measure_colors.get(meas, '#FFFFFF')),
            locations=loc.spanner_labels(ids=[meas]))

    table = table.cols_label(**{_column_id(meas, hemi): hemi[0].upper()
                                for meas, hemis in _measure_columns(keys)
                                for hemi in hemis})

    return table.tab_options(table_font_size='13px',
                             heading_title_font_size='14px',
                             heading_title_font_weight='bold',
                             container_padding_y='0px',
                             data_row_padding='3px').as_raw_html()


def _coverage(result, n_vertices):
    """
    How much of the surface this term's clusters cover.

    Cluster sizes are counts of vertices, so they divide straight into the
    mesh size the model was fitted on.
    """
    clusters = result.get('cluster_summary') or []
    covered = sum(cluster.get('cluster_size') or 0 for cluster in clusters)

    return covered / n_vertices if n_vertices else 0.0


def _cluster_cell(n_clusters, coverage):
    """The count, with a bar showing how much of the surface it covers."""
    # A term with clusters always shows something: a tenth of a pixel would
    # read as nothing at all
    filled = max(round(styles.COVERAGE_BAR_WIDTH * min(coverage, 1.0), 1), 1.0)

    return (f'<div style="display: flex; align-items: center; '
            f'justify-content: flex-end; gap: 8px">'
            f'<span>{n_clusters}</span>'
            f'<span title="{coverage:.1%} of the surface" '
            f'style="{styles.COVERAGE_TRACK}">'
            f'<span style="{styles.coverage_fill(filled)}"></span>'
            f'</span></div>')


def _cluster_table(summaries, keys):
    """How many clusters each term produced, per measure and hemisphere."""
    # Term order follows the model, not the files: keep the first file's order
    # and append anything only later files mention
    terms = []
    for key in keys:
        results = summaries[key].get('results') or {}
        for term, result in results.items():
            # Without cluster correction a term is summarised by its
            # coefficients alone, and there is no cluster table to draw
            if 'n_clusters' not in result:
                continue
            if term not in terms and term != '(Intercept)':
                terms.append(term)

    if not terms:
        return ''

    frame = {'label': terms}
    for key in keys:
        results = summaries[key].get('results') or {}
        n_vertices = summaries[key].get('n_vertices')

        column = []
        for term in terms:
            result = results.get(term) or {}
            n_clusters = result.get('n_clusters')

            if not n_clusters:
                # No clusters, or no such term in this model: both mean
                # 'nothing to open here', and a dot is easier to skip over
                # than a zero -- and there is no coverage to draw
                column.append(NO_CLUSTERS)
            else:
                column.append(_cluster_cell(n_clusters,
                                            _coverage(result, n_vertices)))

        frame[_column_id(*key)] = column

    return _gt_html(pd.DataFrame(frame),
                    'Number and size of significant clusters', keys,
                    as_html=True, bold_stub=True)


def _fit_rows(summaries, keys):
    """[(label, [value per key])] for the statistics that are present."""
    def fit(key):
        return summaries[key].get('model_fit') or {}

    rows = []

    for name in ('AIC', 'Conditional R²', 'Marginal R²'):
        digits = 2 if 'R²' in name else 0
        values = [(fit(key).get(name) or {}).get('median') for key in keys]
        if any(v is not None for v in values):
            rows.append((name, [_fmt(v, digits) for v in values]))

    # Grouping factors vary by model, so take them from the files themselves
    icc_names = []
    for key in keys:
        for name in (fit(key).get('ICC') or {}):
            if name not in icc_names:
                icc_names.append(name)

    for name in icc_names:
        values = [((fit(key).get('ICC') or {}).get(name) or {}).get('median')
                  for key in keys]
        rows.append((f'ICC {name}', [_fmt(v, 2) for v in values]))

    # As a share of the vertices: the raw count means little without knowing
    # how many models were fitted
    singular = [(fit(key).get('Singular fits') or {}).get('percent')
                for key in keys]
    def share(count, percent):
        # No singular fit at all reads as a dot, like a term with no clusters.
        # Where there were some, the percentage is shown -- and a percentage
        # that has rounded down to nothing becomes '<0.01%', so a handful of
        # singular fits out of 160,000 vertices cannot look like none.
        if count is None and percent is None:
            return '--'
        if not count:
            return NO_CLUSTERS
        if not percent:
            # A plain '<': great-tables escapes this table's cells itself, and
            # pre-escaping it here would print the entity
            return '<0.1%'
        return f'{_fmt(percent, 1)}%'

    if any(v is not None for v in singular):
        counts = [(fit(key).get('Singular fits') or {}).get('count')
                  for key in keys]
        rows.append(('singular fits',
                     [share(count, percent)
                      for count, percent in zip(counts, singular)]))

    return rows


def _fit_table(summaries, keys):
    """The fit statistics, laid out so they can be compared across the maps."""
    rows = _fit_rows(summaries, keys)
    if not rows:
        return ''

    frame = {'label': [label for label, _ in rows]}
    for position, key in enumerate(keys):
        frame[_column_id(*key)] = [values[position] for _, values in rows]

    return _gt_html(pd.DataFrame(frame), 'Model fit (median across vertices)',
                    keys)


FULL_MESH = 163842  # fsaverage; anything coarser is flagged as low resolution


def _is_low_res(summary):
    """Whether this model was fitted on something coarser than the full mesh."""
    n_vertices = summary.get('n_vertices')

    return bool(n_vertices) and n_vertices < FULL_MESH


def _low_res_note(summary):
    """Say so, in the fold's own line, so it shows while the model is closed."""
    if not _is_low_res(summary):
        return ''

    return (f'<span style="{styles.LOW_RES_NOTE}" '
            f'title="fitted on {summary["n_vertices"]:,} vertices, not the '
            f'full {FULL_MESH:,}">*low-res</span>')


def summary_block(model_name, summaries, open_=False):
    """
    One model, as verywise described it, folded away behind its name and
    formula so that a folder full of models still reads as a list.
    """
    keys = sorted(summaries)                 # (measure, hemisphere)
    first = summaries[keys[0]]

    formula = ' '.join(str(first.get('model', '')).split())

    return (f'<details{" open" if open_ else ""} '
            f'style="{styles.summary_details(_is_low_res(first))}">'
            f'<summary><b>{model_name}</b>&emsp;<code>{formula}</code>'
            f'{_low_res_note(first)}</summary>'
            f'<div style="{styles.SUMMARY_BODY}">'
            f'<div style="margin-top: 6px">{_scale_line(first)}</div>'
            f'<div style="{styles.SUMMARY_TABLE_ROW}">'
            f'<div>{_cluster_table(summaries, keys)}</div>'
            f'<div>{_fit_table(summaries, keys)}</div>'
            f'</div></div>'
            f'</details>')


def describe_input_folder(model_dict):

    tab_spacing = '&emsp;&emsp;&emsp;'  # space between the "columns"
    info_text = ''
    # great-tables writes a <style> block per table, and markdown would treat
    # the blank lines inside it as the end of the HTML, so described models are
    # kept apart and passed through as HTML
    described_blocks = []
    grouped = has_groups(model_dict)  # folders worth naming, or all in one
    n_described = 0  # counted across the whole folder: in verywise results a
                     # group holds a single model, so a per-group count would
                     # leave every block open
    for dir in sorted(model_dict['results'].keys()):

        sub_dir_df = model_dict['results'][dir]

        # Models that verywise described for us get a block of their own; the
        # rest keep the plain measure / hemisphere listing below
        described = []
        for sub_model in sorted(sub_dir_df.model.unique()):
            summaries = model_summaries(model_dict, f'{dir}/{sub_model}')
            if summaries:
                described.append(summary_block(
                    sub_model, summaries, open_=n_described == 0))
                n_described += 1

        if described:
            if grouped:
                # Name the folder, and indent what came out of it
                described_blocks.append(
                    f'<div style="{styles.GROUP_HEADING}">{dir}</div>'
                    f'<div style="{styles.GROUP_BODY}">{"".join(described)}</div>')
            else:
                described_blocks.extend(described)
            continue

        sub_text = f'</br>&emsp;**{dir}**<table>'
        for sub_model in sorted(sub_dir_df.model.unique()):

            sub_mod_df = sub_dir_df.loc[sub_dir_df.model == sub_model]

            # Extract the outcomes (measures) examines in each model
            avail_meas = sorted(sub_mod_df.meas.unique())
            avail_meas_text = f'</br>{tab_spacing}'.join(f'<span style="background-color:{styles.measure_colors[meas]};'
                                                         f'border-radius:16px;">'
                                                         f' {meas}&nbsp;</span>' for meas in avail_meas)

            hemi_rows = []
            for sub_meas in avail_meas:
                sub_meas_df = sub_mod_df.loc[sub_mod_df.meas == sub_meas]
                avail_hemi = sorted(sub_meas_df.hemi.unique())
                hemi_rows.append('&ensp;'.join(f'<span style="background-color:{styles.VW_COLOR_PALETTE["light-blue"]};'
                                               f'border-radius:16px;">'
                                               f' {hemi[0].upper()}&nbsp;</span>' for hemi in avail_hemi))

            avail_hemi_text = f'</br>{tab_spacing}'.join(hemi_rows)

            sub_table = f'<td VALIGN=TOP>{tab_spacing}{sub_model}</td>' \
                        f'<td VALIGN=TOP>{tab_spacing}{avail_meas_text}</td>' \
                        f'<td VALIGN=TOP>{tab_spacing}{avail_hemi_text}</td></tr>'

            sub_text = sub_text + sub_table

        info_text = info_text + sub_text + '</table>'

    return ui.TagList(
        ui.markdown(f'Model summaries:{info_text}</br>'),
        *[ui.HTML(block) for block in described_blocks])
