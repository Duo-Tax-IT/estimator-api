"""Query Salesforce Opportunity records via the shared SOQL client."""
from ..clients import salesforce_client

# Default columns pulled for each Opportunity. Pass `fields=` to override.
DEFAULT_FIELDS = (
    "Id", "Name", "Job_Number__c", "Purchase_Price__c",
    "First_Name_Owner_1__c", "First_Name_Owner_2__c", "First_Name_Owner_3__c",
    "First_Name_Owner_4__c", "First_Name_Owner_5__c",
    "Last_Name_Owner_1__c", "Last_Name_Owner_2__c", "Last_Name_Owner_3__c",
    "Last_Name_Owner_4__c", "Last_Name_Owner_5__c",
    "BuildCost__c", "Property_Address__c", "Property_Address_Street__c",
    "Property_Address_State__c", "Property_Address_City__c", "Property_Address_Postcode__c",
    "Purchase_Date__c", "Report_Start_Date__c", "Build_Date_OC_Date__c",
    "Date_available_for_rent__c", "Settlement_Date__c", "SharePoint_Link__c",
    "RP_Data_Link__c", "Xero_Invoice_Link__c", "StageName",
    "Number_of_Days_from_Deadline_Date__c", "Deadline_Date__c", "Date_of_Enquiry__c",
    "Type_of_Report__c", "DT_Company__c", "Current_Report_Delegation__c",
    "PropertyType__c", "LGA_Council__c", "Guaranteed_Minimum_Deduction_Year_1__c",
    "Secondary_Address_Street__c", "Secondary_Address_State__c",
    "Secondary_Address_Postcode__c", "Secondary_Address_City__c",
    "Build_Date_OC_Date_Secondary__c", "Report_Start_Date_Secondary__c",
    "Secondary_Dwelling_Type_of_Report__c", "PropertyType_2__c",
    "Date_available_for_rent_Secondary__c", "Secondary_Purchase_Date__c",
    "renovation_build_notes__c", "Fillout_Stage_Instructions__c",
    "ownerLivedInTheProperty__c", "Floor_Area__c", "RPData_Property_ID__c",
    "Survey_Options__c", "Email__c", "samePropertyGroup__c", "Opportunity_Notes__c",
    "ClosedBy__r.FirstName", "ClosedBy__r.LastName", "Last_Stage_Change_Date__c",
    "samePropertyGroup__r.Property_Address__c", "LastStageChangeDate",
    "Number_of_Reports__c", "International__c", "First_Time_Referral__c",
    "PropertyTypeS__c", "Multi_Report_Number__c", "Multi_Report_Total__c",
    "Fee_incl__c", "Report_Fee_Formula__c", "Awaiting_Information_Reason__c",
    "Awaiting_Information__c", "Property_Category__c", "Log_Fillout_Stage_Instructions__c",
    "Property_Acquisition_Type__c", "LastStageChangeInDays", "Awaiting_Info_TDS_Dates__c",
    "Awaiting_Info_TDS_Documents__c", "Awaiting_Info_TDS_Other__c",
    "Secondary_Purchase_Price__c", "ownedByCompany__c", "Fillout_Delegation__c",
    "Fillout_Delegation__r.Name", "Fillout_Delegation__r.Email",
    "Current_Report_Delegation_Email__c", "Referred_By__r.logo_url__c",
    "CreatedBy.Name", "CreatedBy.Email", "ClosedBy__r.Email", "exc_GST__c",
    "invoicePaidDate__c", "Hold__c",
)


def _literal(value: str) -> str:
    """Escape a value for use inside a SOQL string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def get_opportunity(opp_id: str, fields: tuple[str, ...] = DEFAULT_FIELDS) -> dict | None:
    """One Opportunity by Id, or None if it doesn't exist."""
    soql = f"SELECT {', '.join(fields)} FROM Opportunity WHERE Id = '{_literal(opp_id)}'"
    records = salesforce_client.query(soql)
    return records[0] if records else None


def list_opportunities(
    stage: str | None = None,
    name_contains: str | None = None,
    exclude_ids: set[str] | None = None,
    limit: int = 200,
    fields: tuple[str, ...] = DEFAULT_FIELDS,
) -> list[dict]:
    """Opportunities (newest close date first), optionally filtered by stage/name.
    `exclude_ids` drops opportunities already processed, so a fresh batch advances
    to new ones. Always scoped to Duo Tax Quantity Surveyors / Capital Works Report."""
    where = [
        "DT_Company__c = 'Duo Tax Quantity Surveyors'",
        "Type_of_Report__c = 'capital works report'",
    ]
    if stage:
        where.append(f"StageName = '{_literal(stage)}'")
    if name_contains:
        where.append(f"Name LIKE '%{_literal(name_contains)}%'")
    if exclude_ids:
        ids = ", ".join(f"'{_literal(i)}'" for i in exclude_ids)
        where.append(f"Id NOT IN ({ids})")
    clause = " WHERE " + " AND ".join(where) if where else ""
    soql = (
        f"SELECT {', '.join(fields)} FROM Opportunity{clause} "
        f"ORDER BY CloseDate DESC, Id LIMIT {int(limit)}"
    )
    return salesforce_client.query(soql)
