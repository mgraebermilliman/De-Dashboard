"""Practice lookups that avoid Freshservice person/department reads (HTTP 403 for our key).

Both tables are copied from SPARK (IT-SPARK repo, Services/DriveMappings.cs and Services/GroupMappings.cs).
"""

import base64
import json
import subprocess

# Freshservice department ID -> name (SPARK DriveMappings.DepartmentNames).
DEPARTMENT_NAMES = {
    14000218908: "CMH", 14000233347: "DSM", 14000291100: "EBC", 14000110133: "Health Research",
    14000093784: "IntelliScript", 14000371442: "MARA", 14000112231: "MicroInsurance",
    14000093799: "Milwaukee Joint", 14000093798: "Philadelphia Health", 14000093783: "Philadelphia Life",
    14000342856: "Pluritem", 14000110491: "Portland Maine Health", 14000110088: "Omaha - Health & Welfare",
    14000110091: "SEATH", 14000110085: "Tampa Health (190)", 14000143736: "Tampa Individual Health (130)",
    14000110101: "Minneapolis Health", 14000110123: "MFP",
}

# Practice admin OU codes (SPARK GroupMappings.PracticeToAdminOUMap values).
PRACTICE_OUS = {
    "CMH", "DSM", "EBACM", "EBC", "HISC", "HRT", "INT", "MARA", "MIC", "MILWM", "MILWO", "OHW", "PHILR",
    "PHILC", "PLU", "SEATH", "SKYS", "TAMPI", "MFP", "TDZ", "MPLSH", "PHILH", "PME", "TAMPH",
}

# Reads e-mail addresses (one per line) on stdin, prints {email: distinguishedName} for those found. Read-only.
_AD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$emails = [Console]::In.ReadToEnd() -split "`r?`n" | Where-Object { $_.Trim() }
$root = [ADSI]'LDAP://DC=milliman,DC=com'
$found = @{}
foreach ($email in $emails) {
    $v = ([string]$email) -replace '\\', '\5c' -replace '\*', '\2a' -replace '\(', '\28' -replace '\)', '\29' -replace "`0", '\00'
    $filter = "(&(objectCategory=person)(objectClass=user)(|(mail=$v)(userPrincipalName=$v)))"
    $searcher = New-Object System.DirectoryServices.DirectorySearcher($root, $filter, [string[]]@('distinguishedName'))
    $result = $searcher.FindOne()
    if ($result) { $found[[string]$email] = [string]$result.Properties['distinguishedname'][0] }
}
$found | ConvertTo-Json -Compress
"""


def practice_from_dn(distinguished_name: str | None) -> str | None:
    """Most specific practice OU in the user's AD path, e.g. 'OU=CMH' -> 'CMH' (SPARK's rule)."""
    if not distinguished_name:
        return None
    codes = [s.strip()[3:].upper() for s in distinguished_name.split(",") if s.strip().upper().startswith("OU=")]
    matches = [code for code in codes if code in PRACTICE_OUS]
    return max(matches, key=len) if matches else None


def ad_practices(emails: list[str], timeout: int = 300) -> tuple[dict[str, str | None], str | None]:
    """Look up each email in Active Directory. Returns ({email: practice}, problem message or None)."""
    emails = sorted({e.strip().lower() for e in emails if e and "@" in e})
    if not emails:
        return {}, None
    encoded = base64.b64encode(_AD_SCRIPT.encode("utf-16-le")).decode()
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            input="\n".join(emails), capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return {}, f"Active Directory practice lookup unavailable ({type(err).__name__})."
    if proc.returncode != 0:
        first_line = (proc.stderr or "").strip().splitlines()[:1]
        return {}, f"Active Directory practice lookup failed ({first_line[0][:200] if first_line else 'no details'})."
    try:
        found = json.loads(proc.stdout or "{}") or {}
    except json.JSONDecodeError:
        return {}, "Active Directory practice lookup returned unreadable output."
    practices = {email.lower(): practice_from_dn(dn) for email, dn in found.items()}
    missing = len(emails) - len(found)
    return practices, (f"{missing} of {len(emails)} people not found in Active Directory." if missing else None)
