"""Signals: the derived calls stored beside an event (plan M3.4).

`scenarios` turns events into ranked what-ifs, `prediction` scores forward outcomes, and
`accuracy` keeps the scoreboard that makes a public track record auditable.
"""

from finscrape.signals.accuracy import *
from finscrape.signals.prediction import *
from finscrape.signals.scenarios import *
