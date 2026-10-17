"""The kiosk's pages, one package each. A page package exports Page (see kiosk.py) and check().

In the repo they live in catalog/pages/, so they're found there too; on a kiosk, autoupdate.py puts them here. Pages
installed from someone's repo (packs.py) are in ~/.local/share/kiosk/pages/, so they're found there as well."""
import os

__path__ += [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "catalog", "pages"),
             os.path.expanduser("~/.local/share/kiosk/pages")]
