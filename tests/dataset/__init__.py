"""
**File:** ``__init__.py``
**Region:** ``ds_provider_planday_py_lib/dataset``

Description
-----------
This module implements a dataset for Planday APIs, focusing on Planday-specific
data products and parameters rather than generic HTTP concerns.

Includes custom serializers/deserializers tailored to Planday's API contract.


"""

from .planday import PlandayDataset, PlandayDatasetSettings

__all__ = ["PlandayDataset", "PlandayDatasetSettings"]
