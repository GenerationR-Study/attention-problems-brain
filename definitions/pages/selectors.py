"""
Choosing which map to show: model -> measure -> term.

Its own module because three of these exist (one on the results page, two on
the compare page) and the cascade between the three dropdowns should only be
written once.
"""
from shiny import module, reactive, render, ui

import definitions.layout_styles as styles
from definitions.backend_results import detect_terms, terms_without_clusters
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
        all_models = {}
        for group in all_results()['results']:
            sub_models = list(all_results()['results'][group]['model'].unique())
            # TMP: names are kept as they are
            all_models[group] = dict(zip([f'{group}/{m}' for m in sub_models],
                                         sub_models))

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

        avail_terms = detect_terms(all_results=all_results(),
                                   which_model=which_model,
                                   which_meas=which_meas)

        # Terms that found nothing for this measure would only ever draw an
        # empty brain, so they are shown but cannot be chosen
        empty = terms_without_clusters(all_results(), which_model, which_meas)

        unselectable = {str(stack) for stack, term in avail_terms.items()
                        if term in empty}

        # ...which means the starting choice has to be one of the others.
        # Keys are stack numbers, and `selected` is matched against the key
        # itself, so a stringified one would silently match nothing.
        selectable = [stack for stack in avail_terms
                      if str(stack) not in unselectable]

        return mark_unselectable(
            ui.input_selectize(id='select_term', label='Choose term',
                               choices=avail_terms,
                               selected=selectable[0] if selectable else None,
                               width='100%'),
            unselectable)

    @reactive.Calc
    def selection():
        return input.select_model(), input.select_term(), input.select_measure()

    return selection
