"""Example agreements for regression tests and manual testing.

Each pins a behaviour that once went wrong (noted beside it). Like
make_fixture.py, these are for testing parsing and scoring ONLY: synthetic
agreements must never enter a reference corpus.

    python tests/fixtures/contracts.py ~/Desktop/kwys-test-contracts
"""

from __future__ import annotations

import sys
from pathlib import Path

# A Maharashtra leave-and-licence agreement. Says "licence fee", not "rent";
# its "may terminate ... by giving seven (7) days notice" once tied between
# notice and termination and was dropped.
HARSH_LEASE = [
    ("H1", "LEAVE AND LICENCE AGREEMENT"),
    ("P", "This Agreement is made at Pune on this 2nd day of June 2026 between Mrs. R. "
          "Deshpande, residing at Koregaon Park, Pune (hereinafter referred to as the "
          "\"LICENSOR\") of the ONE PART and Mr. V. Iyer (hereinafter referred to as the "
          "\"LICENSEE\") of the OTHER PART."),
    ("H2", "1. TERM AND LOCK-IN"),
    ("P", "1.1 This licence shall be for a period of eleven (11) months commencing on 1st "
          "July 2026."),
    ("P", "1.2 The Licensee shall not terminate this agreement before the expiry of a "
          "lock-in period of eleven (11) months. If the Licensee vacates earlier, the rent "
          "for the remaining lock-in period shall be forfeited from the deposit."),
    ("H2", "2. LICENCE FEE AND DEPOSIT"),
    ("P", "2.1 The Licensee shall pay a monthly licence fee of Rs. 45,000/- (Rupees Forty "
          "Five Thousand only) on or before the 1st day of each month."),
    ("P", "2.2 The Licensee shall pay an interest-free refundable security deposit of "
          "Rs. 4,50,000/- (Rupees Four Lakh Fifty Thousand only), being ten (10) months' "
          "licence fee."),
    ("P", "2.3 The deposit shall be refunded within one hundred and twenty (120) days of "
          "the Licensee handing over vacant possession, after deducting any dues."),
    ("P", "2.4 The licence fee shall be increased by fifteen percent (15%) every eleven "
          "(11) months."),
    ("P", "2.5 Any delay in payment shall attract a late fee of 5% per month on the "
          "amount outstanding."),
    ("H2", "3. MAINTENANCE AND ACCESS"),
    ("P", "3.1 The Licensee shall bear the cost of all repairs, minor or major, up to "
          "Rs. 25,000/- per occasion."),
    ("P", "3.2 The Licensor may enter the premises at any time without notice for "
          "inspection or to show the premises to prospective licensees."),
    ("P", "3.3 The Licensee shall not keep pets or receive overnight guests without the "
          "prior written consent of the Licensor."),
    ("H2", "4. NOTICE"),
    ("P", "4.1 The Licensee shall give three (3) months prior written notice to vacate."),
    ("P", "4.2 The Licensor may terminate this licence by giving seven (7) days written "
          "notice to the Licensee."),
    ("H2", "5. DISPUTES"),
    ("P", "5.1 Any dispute shall be referred to a sole arbitrator nominated by the "
          "Licensor, and the seat of arbitration shall be at Kolkata."),
    ("P", "5.2 The courts at Kolkata alone shall have exclusive jurisdiction."),
    ("H2", "6. INDEMNITY"),
    ("P", "6.1 The Licensee shall indemnify the Licensor against all losses, claims and "
          "expenses of whatever nature arising in connection with the premises."),
    ("P", "IN WITNESS WHEREOF the parties have signed this agreement on the date first "
          "written above."),
]

# Ordinary terms. Once produced false "missing" findings for notice,
# termination and disputes, all of which are present.
FAIR_LEASE = [
    ("H1", "RENTAL AGREEMENT"),
    ("P", "This Rental Agreement is made at Bengaluru on 10th August 2026 between Mr. K. "
          "Rao (hereinafter the \"LANDLORD\") and Ms. P. Menon (hereinafter the "
          "\"TENANT\")."),
    ("H2", "1. TERM"),
    ("P", "1.1 The tenancy shall be for eleven (11) months from 1st September 2026, "
          "renewable by mutual consent."),
    ("P", "1.2 There shall be a lock-in period of three (3) months, binding on both "
          "parties."),
    ("H2", "2. RENT AND DEPOSIT"),
    ("P", "2.1 The Tenant shall pay a monthly rent of Rs. 28,000/- on or before the 5th "
          "day of each month."),
    ("P", "2.2 The Tenant has paid a refundable security deposit of Rs. 56,000/-, being "
          "two (2) months' rent."),
    ("P", "2.3 The deposit shall be refunded within thirty (30) days of the Tenant "
          "handing over possession, less any amounts lawfully due."),
    ("P", "2.4 Rent shall be increased by five percent (5%) on renewal."),
    ("H2", "3. MAINTENANCE AND ACCESS"),
    ("P", "3.1 The Tenant shall bear minor repairs up to Rs. 1,000/- per occasion. "
          "Structural and major repairs shall be the responsibility of the Landlord."),
    ("P", "3.2 The Landlord may inspect the premises after giving at least twenty-four "
          "(24) hours written notice to the Tenant."),
    ("H2", "4. NOTICE AND TERMINATION"),
    ("P", "4.1 The Tenant shall give one (1) month written notice to vacate."),
    ("P", "4.2 The Landlord shall give one (1) month written notice to terminate."),
    ("H2", "5. DISPUTE RESOLUTION"),
    ("P", "5.1 The courts at Bengaluru shall have jurisdiction over any dispute arising "
          "out of this agreement."),
    ("P", "IN WITNESS WHEREOF the parties have signed below."),
]

# Mirror image: generous to the tenant, so it should flag things for the
# LANDLORD. Once gave identical output for both roles.
TENANT_FRIENDLY_LEASE = [
    ("H1", "LEASE DEED"),
    ("P", "This Lease Deed is made at Hyderabad on 1st September 2026 between Mr. S. "
          "Reddy (hereinafter the \"LESSOR\") and Mr. A. Khan (hereinafter the "
          "\"LESSEE\")."),
    ("H2", "1. TERM"),
    ("P", "1.1 The lease shall be for twenty-four (24) months from 1st October 2026."),
    ("P", "1.2 The Lessor shall not terminate this lease during a lock-in period of "
          "twenty-four (24) months. The Lessee is not subject to any lock-in."),
    ("H2", "2. RENT AND DEPOSIT"),
    ("P", "2.1 The Lessee shall pay a monthly rent of Rs. 22,000/-."),
    ("P", "2.2 The Lessee shall pay a security deposit of Rs. 11,000/-, being half (0.5) "
          "a month's rent."),
    ("P", "2.3 The rent shall not be increased during the term of this lease."),
    ("H2", "3. NOTICE"),
    ("P", "3.1 The Lessee may vacate by giving fifteen (15) days written notice."),
    ("P", "3.2 The Lessor shall give six (6) months written notice to terminate."),
    ("H2", "4. REPAIRS"),
    ("P", "4.1 The Lessor shall bear all repairs, including minor repairs, at his own "
          "cost within seven (7) days of being informed."),
    ("H2", "5. JURISDICTION"),
    ("P", "5.1 The courts at Hyderabad shall have jurisdiction."),
]

EMPLOYMENT = [
    ("H1", "LETTER OF APPOINTMENT"),
    ("P", "This letter of appointment is issued by Brightpath Technologies Private Limited "
          "(hereinafter the \"COMPANY\") to Ms. D. Sharma (hereinafter the \"EMPLOYEE\") "
          "on 15th September 2026."),
    ("H2", "1. POSITION AND PROBATION"),
    ("P", "1.1 The Employee is appointed as Associate Software Engineer at an annual "
          "cost to company of Rs. 6,00,000/-."),
    ("P", "1.2 The Employee shall be on probation for a period of twelve (12) months, "
          "which the Company may extend at its sole discretion."),
    ("H2", "2. SERVICE BOND"),
    ("P", "2.1 In consideration of the training provided, the Employee shall serve the "
          "Company for a minimum period of thirty-six (36) months from the date of "
          "joining."),
    ("P", "2.2 If the Employee leaves before completing the bond period, the Employee "
          "shall pay the Company liquidated damages of Rs. 3,00,000/- (Rupees Three Lakh "
          "only)."),
    ("H2", "3. NOTICE PERIOD"),
    ("P", "3.1 The Employee shall give three (3) months written notice of resignation."),
    ("P", "3.2 The Company may terminate the employment by giving seven (7) days notice "
          "or salary in lieu thereof."),
    ("H2", "4. NON-COMPETE"),
    ("P", "4.1 For a period of twenty-four (24) months after leaving the Company, the "
          "Employee shall not join any competitor or client of the Company anywhere in "
          "India."),
    ("H2", "5. DISPUTES"),
    ("P", "5.1 Any dispute shall be referred to arbitration seated at Chennai, and the "
          "courts at Chennai alone shall have jurisdiction."),
    ("P", "Please sign and return a copy of this letter as a token of your acceptance."),
]

TOS = [
    ("H1", "TERMS OF SERVICE — STREAMLY"),
    ("P", "Please read these Terms carefully. By accessing or using the Streamly app or "
          "website you agree to be bound by these Terms."),
    ("H2", "1. Acceptance"),
    ("P", "1. By creating an account, or simply by browsing the service, you accept "
          "these Terms in full."),
    ("H2", "2. Changes"),
    ("P", "2. We may modify these Terms at any time at our sole discretion without "
          "notice to you. Continued use of the service after any change constitutes "
          "acceptance of the new Terms."),
    ("H2", "3. Content"),
    ("P", "3. We may remove any content you upload, at any time and for any reason, "
          "without notice."),
    ("H2", "4. Termination"),
    ("P", "4. We may suspend or terminate your account at any time, for any reason or "
          "no reason, without notice or liability."),
    ("H2", "5. Liability"),
    ("P", "5. To the maximum extent permitted by law, Streamly shall not be liable for "
          "any indirect, incidental or consequential damages, loss of data or loss of "
          "profits, and our total liability shall not exceed Rs. 500."),
    ("H2", "6. Disputes"),
    ("P", "6. Any dispute shall be resolved exclusively by binding individual "
          "arbitration. You waive any right to a jury trial or to participate in a class "
          "action."),
    ("H2", "7. Governing law"),
    ("P", "7. These Terms are governed by the laws of Singapore, and the courts of "
          "Singapore shall have exclusive jurisdiction."),
    ("H2", "8. Privacy"),
    ("P", "8. We respect your privacy. Please see our Privacy Policy for details of the "
          "data we collect."),
]

# No numbering at all. Segmentation cannot split it, so nothing may be
# claimed missing from it.
UNNUMBERED = [
    ("P", "Rental arrangement between Mr. J. Thomas, the owner, and Ms. N. Gupta, the "
          "tenant, for the flat at Andheri West, Mumbai."),
    ("P", "The tenant will pay rent of Rs. 38,000 every month before the 7th. A deposit "
          "of eight months rent, that is Rs. 3,04,000, has been paid and will be returned "
          "when the tenant leaves, after the owner has checked the flat."),
    ("P", "The tenant must tell the owner three months before leaving. The owner can ask "
          "the tenant to leave with fifteen days notice if the owner needs the flat."),
    ("P", "The owner can visit the flat whenever needed. The tenant pays for all repairs "
          "inside the flat. Any disagreement will be settled in the courts at Delhi."),
    ("P", "Signed by both parties at Mumbai."),
]

ALL = {
    "01_lease_harsh_on_tenant": HARSH_LEASE,
    "02_lease_fair": FAIR_LEASE,
    "03_lease_generous_to_tenant": TENANT_FRIENDLY_LEASE,
    "06_lease_unnumbered_prose": UNNUMBERED,
    "07_job_offer_with_bond": EMPLOYMENT,
    "08_app_terms_of_service": TOS,
}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    from make_fixture import build

    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser()
    out.mkdir(parents=True, exist_ok=True)
    for name, blocks in ALL.items():
        print(build(blocks, out / f"{name}.pdf"))
