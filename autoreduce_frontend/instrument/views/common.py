import base64
from autoreduce_qp.queue_processor.variable_utils import VariableUtils
from django.http.request import QueryDict


def _combine_dicts(current: dict, default: dict):
    """
    Combine the current and default variable dictionaries, into a single
    dictionary which can be more easily rendered into the webapp.

    If no current variables are provided, return the default as both current and
    default.
    """
    if not current:
        current = default.copy()

    final = {}
    for name, var in current.items():
        final[name] = {"current": var, "default": default.get(name, None)}

    return final


def get_vars_from_run(reduction_run):
    vars_kwargs = reduction_run.arguments.as_dict()
    standard_vars = vars_kwargs["standard_vars"]
    advanced_vars = vars_kwargs["advanced_vars"]

    try:
        default_variables = VariableUtils.get_default_variables(reduction_run.instrument.name)
        default_standard_variables = default_variables["standard_vars"]
        default_advanced_variables = default_variables["advanced_vars"]
        variable_help = default_variables["variable_help"]
    except (FileNotFoundError, ImportError, SyntaxError):
        default_variables = {}
        default_standard_variables = {}
        default_advanced_variables = {}
        variable_help = {}

    final_standard = _combine_dicts(standard_vars, default_standard_variables)
    final_advanced = _combine_dicts(advanced_vars, default_advanced_variables)

    return final_standard, final_advanced, variable_help


def decode_b64(value: str):
    """
    Decodes the base64 representation back to utf-8 string.
    """
    return base64.urlsafe_b64decode(value).decode("utf-8")


def read_variables_from_form_post_submit(post_data: QueryDict) -> dict:
    """Process the variables submitted in the request's POST data
    and return a dictionary containing the standard and advanced variables

    :param post_data: The request's POST dictionary. It will be filtered for variables
    :return: Dictionary containign standard_vars and advanced_vars keys.
    """

    # [(startswith+name, value) or ("var-advanced-"+name, value)]
    var_list = [t for t in post_data.items() if t[0].startswith("var-")]

    def _decode_dict(var_list, startswith: str):
        return {decode_b64(var[0].replace(startswith, "")): var[1] for var in var_list if var[0].startswith(startswith)}

    standard_vars = _decode_dict(var_list, "var-standard-")
    advanced_vars = _decode_dict(var_list, "var-advanced-")
    return {"standard_vars": standard_vars, "advanced_vars": advanced_vars}
