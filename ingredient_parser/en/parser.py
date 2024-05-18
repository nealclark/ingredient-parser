#!/usr/bin/env python3

from importlib.resources import as_file, files

import pycrfsuite

from .._common import group_consecutive_idx
from ..dataclasses import ParsedIngredient, ParserDebugInfo
from ._utils import pluralise_units
from .postprocess import PostProcessor
from .preprocess import PreProcessor

# Create TAGGER object that can be reused between function calls
# We only want to load the model into TAGGER once, but only do it
# when we need to (from parse_ingredient() or inspect_parser()) and
# not whenever anything from ingredient_parser is imported.
TAGGER = pycrfsuite.Tagger()


def load_model_if_not_loaded():
    """Load model into TAGGER variable if not loaded.

    There isn't a simple way to check if the model if loaded or not, so
    we try to call TAGGER.info() which will raise a RuntimeError if the
    model is not loaded yet.
    """
    try:
        TAGGER.info()
    except RuntimeError:
        with as_file(files(__package__) / "model.en.crfsuite") as p:
            TAGGER.open(str(p))


def parse_ingredient_en(
    sentence: str,
    discard_isolated_stop_words: bool = True,
    string_units: bool = False,
    imperial_units: bool = False,
) -> ParsedIngredient:
    """Parse an English language ingredient sentence to return structured data.

    Parameters
    ----------
    sentence : str
        Ingredient sentence to parse
    discard_isolated_stop_words : bool, optional
        If True, any isolated stop words in the name, preparation, or comment fields
        are discarded.
        Default is True.
    string_units : bool
        If True, return all IngredientAmount units as strings.
        If False, convert IngredientAmount units to pint.Unit objects where possible.
        Dfault is False.
    imperial_units : bool
        If True, use imperial units instead of US customary units for pint.Unit objects
        for the the following units: fluid ounce, cup, pint, quart, gallon.
        Default is False, which results in US customary units being used.
        This has no effect if string_units=True.

    Returns
    -------
    ParsedIngredient
        ParsedIngredient object of structured data parsed from input string
    """
    load_model_if_not_loaded()

    processed_sentence = PreProcessor(sentence)
    tokens = processed_sentence.tokenized_sentence
    labels = TAGGER.tag(processed_sentence.sentence_features())
    scores = [TAGGER.marginal(label, i) for i, label in enumerate(labels)]

    # Re-pluralise tokens that were singularised if the label isn't UNIT
    # For tokens with UNIT label, we'll deal with them below
    for idx in processed_sentence.singularised_indices:
        token = tokens[idx]
        label = labels[idx]
        if label != "UNIT":
            tokens[idx] = pluralise_units(token)

    if all(label != "NAME" for label in labels):
        # No tokens were assigned the NAME label, so guess if there's a name
        labels, scores = guess_ingredient_name(labels, scores)

    postprocessed_sentence = PostProcessor(
        sentence,
        tokens,
        labels,
        scores,
        discard_isolated_stop_words=discard_isolated_stop_words,
        string_units=string_units,
        imperial_units=imperial_units,
    )
    return postprocessed_sentence.parsed


def inspect_parser_en(
    sentence: str,
    discard_isolated_stop_words: bool = True,
    string_units: bool = False,
    imperial_units: bool = False,
) -> ParserDebugInfo:
    """Dataclass for holding intermediate objects generated during parsing.

    Parameters
    ----------
    sentence : str
        Ingredient sentence to parse
    discard_isolated_stop_words : bool, optional
        If True, any isolated stop words in the name, preparation, or comment fields
        are discarded.
        Default is True.
    string_units : bool
        If True, return all IngredientAmount units as strings.
        If False, convert IngredientAmount units to pint.Unit objects where possible.
        Dfault is False.
    imperial_units : bool
        If True, use imperial units instead of US customary units for pint.Unit objects
        for the the following units: fluid ounce, cup, pint, quart, gallon.
        Default is False, which results in US customary units being used.
        This has no effect if string_units=True.

    Returns
    -------
    ParserDebugInfo
        ParserDebugInfo object containing the PreProcessor object, PostProcessor
        object and Tagger.
    """
    load_model_if_not_loaded()

    processed_sentence = PreProcessor(sentence)
    tokens = processed_sentence.tokenized_sentence
    labels = TAGGER.tag(processed_sentence.sentence_features())
    scores = [TAGGER.marginal(label, i) for i, label in enumerate(labels)]

    # Re-plurise tokens that were singularised if the label isn't UNIT
    # For tokens with UNIT label, we'll deal with them below
    for idx in processed_sentence.singularised_indices:
        token = tokens[idx]
        label = labels[idx]
        if label != "UNIT":
            tokens[idx] = pluralise_units(token)

    if all(label != "NAME" for label in labels):
        # No tokens were assigned the NAME label, so guess if there's a name
        labels, scores = guess_ingredient_name(labels, scores)

    postprocessed_sentence = PostProcessor(
        sentence,
        tokens,
        labels,
        scores,
        discard_isolated_stop_words=discard_isolated_stop_words,
        string_units=string_units,
        imperial_units=imperial_units,
    )

    return ParserDebugInfo(
        sentence=sentence,
        PreProcessor=processed_sentence,
        PostProcessor=postprocessed_sentence,
        tagger=TAGGER,
    )


def guess_ingredient_name(
    labels: list[str], scores: list[float]
) -> tuple[list[str], list[float]]:
    """Guess ingredient name from list of labels and scores.

    This only applies if the token labelling resulted in no tokens being assigned the
    NAME label. When this happens, calculate the confidence of each token being NAME,
    and select the most likely value if the confidence is greater than 0.2.
    If there are consecutive tokens that meet that criteria, give them all the NAME
    label.

    Parameters
    ----------
    labels : list[str]
        List of labels
    scores : list[float]
        List of scores

    Returns
    -------
    list[str], list[float]
        Labels and scores, modified to assign a name if possible.
    """
    # Calculate confidence of each token being labelled NAME and get indices where that
    # confidence is greater than 0.2.
    name_scores = [TAGGER.marginal("NAME", i) for i, _ in enumerate(labels)]
    candidate_indices = [i for i, score in enumerate(name_scores) if score >= 0.2]

    if len(candidate_indices) == 0:
        return labels, scores

    # Group candidate indices into groups of consecutive indices and order by longest
    groups = [list(group) for group in group_consecutive_idx(candidate_indices)]

    # Take longest group
    indices = sorted(groups, key=len)[0]
    for i in indices:
        labels[i] = "NAME"
        scores[i] = name_scores[i]

    return labels, scores
