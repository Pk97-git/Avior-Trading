"""
engines/
========
Stateless classifiers — pure logic, no DB writes.
Each engine reads from the DB and returns a structured classification.

  regime.py          → MacroRegimeClassifier  (5-state regime label)
  sector_rotation.py → SectorRotationEngine   (4W/12W ETF relative strength)
  compounder.py      → CompoundersEngine      (long-term quality filter)
"""
