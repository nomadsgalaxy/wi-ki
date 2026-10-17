"""The kiosk's pages, one package each. A page package exports Page (see kiosk.py) and check().

In the repo they live in catalog/pages/, so they're found there too; on a kiosk, autoupdate.py puts them here."""
import os

__path__.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "catalog", "pages"))
