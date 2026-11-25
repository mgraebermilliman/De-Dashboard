"""Short names for Freshservice departments.

The practice of a person is the department on their own Freshservice account. This table is copied from SPARK
(IT-SPARK repo, Services/DriveMappings.cs) and gives the usual short name where there is one ("CMH Health" ->
"CMH"); any other department keeps the name Freshservice has. Active Directory is not used any more (Michael,
2026-11-25); it's in the git history if it's ever needed again.
"""

# Freshservice department ID -> name (SPARK DriveMappings.DepartmentNames).
DEPARTMENT_NAMES = {
    14000218908: "CMH", 14000233347: "DSM", 14000291100: "EBC", 14000110133: "Health Research",
    14000093784: "IntelliScript", 14000371442: "MARA", 14000112231: "MicroInsurance",
    14000093799: "Milwaukee Joint", 14000093798: "Philadelphia Health", 14000093783: "Philadelphia Life",
    14000342856: "Pluritem", 14000110491: "Portland Maine Health", 14000110088: "Omaha - Health & Welfare",
    14000110091: "SEATH", 14000110085: "Tampa Health (190)", 14000143736: "Tampa Individual Health (130)",
    14000110101: "Minneapolis Health", 14000110123: "MFP",
}
