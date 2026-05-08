"""
**File:** ``enums.py``
**Region:** ``ds_provider_planday_py_lib/enums``

Constants for Planday provider.

Example:
    >>> ResourceType.PLANDAY_LINKED_SERVICE
    ds.resource.linked-service.planday

"""

from enum import StrEnum

from ds_protocol_http_py_lib.enums import AuthType


class PlandayConstants:
    """Planday API constants - same for all users"""

    # OAuth2 Endpoints (provided by Planday)
    TOKEN_ENDPOINT = "https://openapi.planday.com/oauth/token"  # nosec B105
    """Planday OAuth2 token endpoint"""

    API_HOST = "https://openapi.planday.com/"
    """Planday API base URL"""

    # Authentication Type
    AUTH_TYPE = AuthType.CUSTOM
    """Authentication type for Planday (CUSTOM for OAuth2 handling)"""


class ResourceType(StrEnum):
    """
    Constants for Planday provider.
    """

    PLANDAY_LINKED_SERVICE = "ds.resource.linked-service.planday"
    PLANDAY_DATASET = "ds.resource.dataset.planday"


class PlandayDataProducts(StrEnum):
    """Available Planday data products"""

    # HR
    EMPLOYEES = "employees"
    DEPARTMENTS = "departments"
    EMPLOYEE_GROUPS = "employee_groups"
    EMPLOYEE_TYPE = "employee_types"
    EMPLOYEE_ACCOUNT_MANAGEMENT = "employee_account_management"
    EMPLOYEE_HISTORY = "employee_history"
    CUSTOM_PROPERTY_ATTACHMENT_VALUES = "custom_property_attachment_values"
    SKILLS = "skills"

    # Pay
    PAY_RATES = "default_pay_rates"
    ALLOCATIONS = "allocations"
    DEFAULT_PAY_RATES = "default_pay_rates"
    EMPLOYEE_SALARIES = "employee_salaries"
    SALARIES = "salaries"
    SALARY_IDENTIFIERS = "salary_identifiers"

    # Payroll
    PAYROLL = "payroll"

    # Portal
    PORTAL = "portal"

    # Punch Clock
    BREAKS = "breaks"
    EMPLOYEE_SHIFTS = "employee_shifts"
    PUNCH_CLOCK_SHIFTS = "punch_clock_shifts"

    # Reports
    SCHEDULING_HISTORY = "scheduling_history"

    # SCHEDULE
    SHIFTS = "shifts"
    SECTIONS = "sections"
    POSITIONS = "positions"
    SHIFT_TYPES = "shift_types"
    TIME_AND_COST = "time_and_cost"
    SHIFT_HISTORY = "shift_history"
    SCHEDULE_DAY = "schedule_day"

    # SECURITY_GROUPS_MEMBERSHIP
    SECURITY_GROUPS = "security_groups"

    # Contact Rules
    CONTACT_RULES = "contact_rules"
    CONTACT_RULES_EMPLOYEES = "contact_rules_employees"

    # ABSENCE
    ACCOUNTS = "accounts"
    ADJUSTMENTS = "adjustments"
    ACCOUNT_TYPES = "account_types"
    ABSENCE_REQUESTS = "absence_requests"
    ACCOUNT_VALUES = "account_values"
    TOIL_TRANSACTIONS = "toil_transactions"


class PlandaySection(StrEnum):
    """Planday API sections"""

    HR = "HR"
    PAY = "Pay"
    PAYROLL = "Payroll"
    PUNCH_CLOCK = "Punch Clock"
    CONTACT_RULES = "Contact Rules"
    ABSENCE = "Absence"
    PORTAL = "Portal"
    SCHEDULE = "Schedule"
    REPORTS = "Reports"
    SECURITY_GROUPS_MEMBERSHIP = "Security Groups Membership"
    REVENUE = "Revenue"
