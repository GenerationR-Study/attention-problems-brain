"""
Choosing which map to show: model -> measure -> term.

Its own module because three of these exist (one on the results page, two on
the compare page) and the cascade between the three dropdowns should only be
written once.
"""
from shiny import module, reactive, render, ui

import definitions.layout_styles as styles
from definitions.backend_results import (
    has_groups, term_groups, terms_without_clusters,
)
from definitions.pages.common import mark_unselectable


@module.ui
def map_selector_ui():
    """
    Three dropdowns, filled in once a results folder has been read.

    Shown as model | term | measure. The cascade behind them runs
    model -> measure -> term, but that is the server's business: this order is
    the one that reads best.
    """
    return ui.TagList(
        ui.output_ui('model_ui'),
        ui.output_ui('term_ui'),
        ui.output_ui('measure_ui'))


@module.server
def map_selector_server(input, output, session, all_results):
    """Fill the dropdowns in; return a reactive giving (model, term, measure)."""

    @render.ui
    def model_ui():
        results = all_results()['results']

        # Nested results keep their folders as groups in the dropdown; a flat
        # folder would otherwise put every model under a heading of its own
        grouped = has_groups(all_results())

        all_models = {}
        for group in results:
            sub_models = list(results[group]['model'].unique())
            # TMP: names are kept as they are
            choices = dict(zip([f'{group}/{m}' for m in sub_models], sub_models))

            if grouped:
                all_models[group] = choices
            else:
                all_models.update(choices)

        return ui.input_selectize(id='select_model',
                                  label='Choose model',
                                  choices=all_models, width='100%')

    @render.ui
    def measure_ui():
        group, model = input.select_model().split('/', 1)

        group_df = all_results()['results'][group]
        meas_list = list(group_df[group_df.model == model]['meas'].unique())

        return ui.input_selectize(
            id='select_measure', label='Choose measure',
            choices={key: styles.measure_names[key] for key in meas_list},
            width='100%')

    @render.ui
    def term_ui():
        which_model, which_meas = input.select_model(), input.select_measure()

        # The model's coefficients, then its random-effect and fit maps
        groups = term_groups(all_results(), which_model, which_meas)

        # Coefficients that found nothing for this measure would only ever
        # draw an empty brain, so they are shown but cannot be chosen. Fit
        # maps are never empty in that sense.
        empty = terms_without_clusters(all_results(), which_model, which_meas)

        unselectable = {str(key) for key, label
                        in groups.get('Fixed effects', {}).items()
                        if label in empty}

        # ...which means the starting choice has to be one of the others.
        # `selected` is matched against the key itself, so a stringified
        # stack number would silently match nothing.
        selectable = [key for group in groups.values() for key in group
                      if str(key) not in unselectable]

        # One group is shown as a plain list, several as labelled groups
        choices = (groups if len(groups) > 1
                   else next(iter(groups.values()), {}))

        return mark_unselectable(
            ui.input_selectize(id='select_term', label='Choose term',
                               choices=choices,
                               selected=selectable[0] if selectable else None,
                               width='100%'),
            unselectable)

    @reactive.Calc
    def selection():
        return input.select_model(), input.select_term(), input.select_measure()

    return selection
