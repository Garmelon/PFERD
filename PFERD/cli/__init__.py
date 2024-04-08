# isort: skip_file

# The order of imports matters because each command module registers itself
# with the parser from ".parser" and the import order affects the order in
# which they appear in the help. Because of this, isort is disabled for this
# file. Also, since we're reexporting or just using the side effect of
# importing itself, we get a few linting warnings, which we're disabling as
# well.

from . import command_local  # noqa: F401 imported but unused
from . import command_ilias_web  # noqa: F401 imported but unused
from . import command_kit_ilias_web  # noqa: F401 imported but unused
from . import command_kit_ipd  # noqa: F401 imported but unused
from .parser import PARSER, ParserLoadError, load_default_section  # noqa: F401 imported but unused
