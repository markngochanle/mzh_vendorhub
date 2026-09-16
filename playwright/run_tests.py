import os
import sys
import time
import sqlite3
import subprocess
import socket
from pathlib import Path

def is_port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
PLAYWRIGHT_DIR = BASE_DIR / "playwright"
SCREENSHOTS_DIR = PLAYWRIGHT_DIR / "screenshots"
UAT_DB_PATH = PLAYWRIGHT_DIR / "uat_db.sqlite3"

# Ensure screenshots dir exists
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# 1. Initialize UAT Database
def init_uat_db():
    print("Initializing UAT test database...")
    if UAT_DB_PATH.exists():
        try:
            UAT_DB_PATH.unlink()
        except Exception as e:
            print(f"Could not delete old UAT DB: {e}. Trying to overwrite.")
            
    # Set environment variables so common.init_db() targets UAT database
    os.environ["DB_PATH"] = str(UAT_DB_PATH)
    
    # Import common after setting env var
    sys.path.append(str(BASE_DIR))
    import common
    common.init_db()
    
    # Insert initial mock data for UAT
    conn = sqlite3.connect(str(UAT_DB_PATH))
    try:
        cur = conn.cursor()
        
        # Insert projects
        cur.execute("""
            INSERT INTO projects (id, short_name, full_name, is_active, os_start_date, os_end_date, created_at, updated_at)
            VALUES (1, 'DOM_EUC', 'DOM EUC Project', 1, '2026-01-01', '2026-12-31', ?, ?)
        """, (common.now_iso(), common.now_iso()))
        
        # Insert Buyer vendor (purchasing = 1)
        cur.execute("""
            INSERT INTO vendors (id, company_name_vi, address_vi, tax_id, purchasing, is_active, created_at, updated_at)
            VALUES (1, 'NGÂN HÀNG MIZUHO', '16 Phan Chu Trinh', '0100234567', 1, 1, ?, ?)
        """, (common.now_iso(), common.now_iso()))
        
        # Insert Seller vendor (purchasing = 0)
        cur.execute("""
            INSERT INTO vendors (id, company_name, company_name_vi, address_vi, tax_id, purchasing, is_active, created_at, updated_at)
            VALUES (2, 'FPT SOFTWARE', 'Công ty FPT Software', 'Duy Tân, Cầu Giấy', '0102135934', 0, 1, ?, ?)
        """, (common.now_iso(), common.now_iso()))
        
        conn.commit()
        print("UAT test database initialized successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Failed to initialize UAT mock data: {e}")
        sys.exit(1)
    finally:
        conn.close()

# 2. Check Playwright dependency
def check_dependencies():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n" + "="*70)
        print("ERROR: Playwright library is not installed in the Python environment.")
        print("Please run the following commands to install dependencies:")
        print("  pip install playwright")
        print("  playwright install chromium")
        print("="*70 + "\n")
        sys.exit(1)

# 3. Start server in background on independent port 8899
def start_server():
    print("Starting local server for UAT on port 8899...")
    os.environ["PORT"] = "8899"
    os.environ["DB_PATH"] = str(UAT_DB_PATH)
    
    server_script = BASE_DIR / "server.py"
    log_file = open(PLAYWRIGHT_DIR / "server.log", "w")
    # Launch server.py as background process
    proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        env=os.environ,
        stdout=log_file,
        stderr=log_file
    )
    
    # Wait for server to bind and respond
    start_time = time.time()
    server_ready = False
    while time.time() - start_time < 5.0:
        if is_port_open("localhost", 8899):
            server_ready = True
            break
        time.sleep(0.2)
        
    if not server_ready:
        print("Error: UAT server did not start on port 8899 within 5 seconds.")
        proc.terminate()
        proc.wait()
        sys.exit(1)
        
    print("UAT server is up and listening on port 8899.")
    return proc, log_file
    
# Support target test case selection (1-7)
target_tc = None
for i, arg in enumerate(sys.argv):
    if arg == "--tc" and i + 1 < len(sys.argv):
        try:
            target_tc = int(sys.argv[i+1])
        except ValueError:
            pass

def should_run_and_show(tc_id):
    if target_tc is None: # Run all
        return True, True
    if tc_id < target_tc: # Run silently for setup
        return True, False
    if tc_id == target_tc: # Run and show
        return True, True
    return False, False # Do not run subsequent TCs

# 4. Run Playwright UAT Scenarios
def run_playwright_tests():
    from playwright.sync_api import sync_playwright
    
    print("\n" + "="*50)
    if target_tc is None:
        print("Starting Playwright UAT Automation Scenarios")
    else:
        print(f"Starting Playwright UAT Scenario {target_tc}")
    print("="*50)
    
    # Support --headed flag if the user wants to see browser
    headed = "--headed" in sys.argv
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=500 if headed else 0)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        
        # Auto-accept all browser dialogs (confirm, alert)
        page.on("dialog", lambda dialog: dialog.accept())
        
        base_url = "http://localhost:8899"
        
        try:
            # -----------------------------------------------------------------
            # UAT 1: Dashboard & Basic Navigation
            # -----------------------------------------------------------------
            run, show = should_run_and_show(1)
            if run:
                if show:
                    print("\n[UAT 1] Checking Dashboard & Menu Navigation...")
                page.goto(base_url)
                page.wait_for_selector("text=Mizuho IT Outsourcing Vendor Hub")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_dashboard.png"))
                
                # Navigate to Vendors
                page.click("text=Vendors")
                page.wait_for_selector("text=Search Vendor")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_vendors.png"))
                
                # Navigate to Contracts
                page.click("text=Contracts")
                page.wait_for_selector("text=+ Add Framework Contract")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_contracts.png"))
                
                # Navigate to Staff
                page.click("text=Staff")
                page.wait_for_selector("text=+ Add Staff")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_staff.png"))
                
                # Navigate to Attendance
                page.click("text=Attendance")
                page.wait_for_selector("text=Import attendance data")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_attendance.png"))
                
                # Navigate to Invoices
                page.click("text=Invoices")
                page.wait_for_selector("text=+ Import Invoice")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_invoices.png"))
                
                # Navigate to Audit Logs
                page.click("text=Audit Logs")
                page.wait_for_selector("text=Search Details")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat1_audit.png"))
                
                if show:
                    print("=> UAT 1 Dashboard & Navigation: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 2: Create a Staff Member
            # -----------------------------------------------------------------
            run, show = should_run_and_show(2)
            if run:
                if show:
                    print("\n[UAT 2] Creating a new Staff Member...")
                page.goto(f"{base_url}/staff/new")
            
                page.fill("input[name='full_name_vi']", "Nguyen UAT Tester")
                page.select_option("select[name='vendor_id']", value="2")  # FPT SOFTWARE
                page.fill("input[name='position']", "Senior QA Automator")
                page.fill("input[name='paid_leave_total_hours']", "12")
                page.fill("input[name='paid_leave_used_hours']", "0")
                page.select_option("select[name='work_shift']", value="8:00 - 17:00")
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat2_new_staff_filled.png"))
                page.click("button[type='submit']")
                
                # Verify UAT Tester is now visible in the list
                page.wait_for_selector("text=Nguyen UAT Tester")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat2_staff_list_success.png"))
                    print("=> UAT 2 Create Staff Member: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 3: Create Framework Contract, Annex, and Allocate Staff
            # -----------------------------------------------------------------
            run, show = should_run_and_show(3)
            if run:
                if show:
                    print("\n[UAT 3] Creating Framework Contract, Annex, and Allocating Staff...")
                
                # 3.1 Create Framework Contract
                page.goto(f"{base_url}/contract/new")
                page.select_option("select[name='buyer_vendor_id']", value="1")   # MIZUHO
                page.select_option("select[name='seller_vendor_id']", value="2")  # FPT
                page.fill("input[name='framework_no']", "MHB/FPT/UAT/001")
                page.fill("input[name='framework_name']", "FPT UAT Test Framework Contract")
                page.fill("input[name='start_date']", "2026-01-01")
                page.fill("input[name='end_date']", "2026-12-31")
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat3_1_new_contract_filled.png"))
                page.click("button[type='submit']")
                page.wait_for_selector("text=+ Add Annex")
                
                # 3.2 Create Annex (Contract ID is 1)
                page.goto(f"{base_url}/annex/new?contract_id=1")
                page.fill("input[name='annex_name']", "Annex UAT 2026-A")
                page.fill("input[name='start_date']", "2026-01-01")
                page.fill("input[name='end_date']", "2026-06-30")
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat3_2_new_annex_filled.png"))
                page.click("button[type='submit']")
                page.wait_for_selector("text=Annex UAT 2026-A")
                
                # 3.3 Allocate Staff to Annex (Staff=1, Contract=1, Annex=1)
                page.goto(f"{base_url}/contract/assign-staff?contract_id=1&annex_id=1")
                page.select_option("select[name='staff_id']", value="1")  # Nguyen UAT Tester
                page.fill("input[name='joining_date']", "2026-01-01")
                page.fill("input[name='tentative_leaving_date']", "2026-06-30")
                page.fill("input[name='monthly_rate']", "55000000")
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat3_3_allocate_staff_filled.png"))
                page.click("button[type='submit']")
                
                # Verify allocated staff in contract view page
                page.wait_for_selector("text=Nguyen UAT Tester")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat3_4_allocation_success.png"))
                    print("=> UAT 3 Create Contract & Annex & Allocate: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 4: Project Assignment Matrix
            # -----------------------------------------------------------------
            run, show = should_run_and_show(4)
            if run:
                if show:
                    print("\n[UAT 4] Assigning Staff to Projects via Matrix...")
                
                # Go to projects assign page
                page.goto(f"{base_url}/projects/assign?project_id=1")
                
                # Select Nguyen UAT Tester
                page.select_option("select[id='add_staff_select']", value="1")
                
                # Check months 2026-01 and 2026-02 (should be enabled after selection)
                page.check("input[name='months'][value='2026-01']")
                page.check("input[name='months'][value='2026-02']")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat4_project_assign_filled.png"))
                
                # Add to project
                page.click("button:has-text('Add Staff to Project')")
                page.wait_for_selector("text=Nguyen UAT Tester")
                
                # Now go to staff edit page to verify matrix toggle
                page.goto(f"{base_url}/staff/edit?id=1")
                
                # Uncheck and check project DOM_EUC (ID=1) for month 2026-01 to test AJAX toggle
                checkbox_selector = "input[data-project-id='1'][data-month='2026-01']"
                page.wait_for_selector(checkbox_selector)
                
                # Uncheck to test AJAX
                page.uncheck(checkbox_selector)
                page.wait_for_timeout(1500)
                
                # Check again (the selector is re-loaded after page reload, so re-wait for selector)
                page.wait_for_selector(checkbox_selector)
                page.check(checkbox_selector)
                page.wait_for_timeout(1500)
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat4_project_matrix_assigned.png"))
                    print("=> UAT 4 Project Matrix Assignment: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 5: Daily Attendance Logging & Lock
            # -----------------------------------------------------------------
            run, show = should_run_and_show(5)
            if run:
                if show:
                    print("\n[UAT 5] Logging Daily Attendance and Locking...")
                page.goto(f"{base_url}/attendance?month=2026-01")
                
                # Input 8 hours for day 1 (2026-01-01)
                att_input_selector = "input[name='w_1_2026-01-01']"
                page.wait_for_selector(att_input_selector)
                page.fill(att_input_selector, "8.0")
                
                # Move focus off to trigger change and AJAX save
                page.press(att_input_selector, "Tab")
                page.wait_for_timeout(1000)
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat5_attendance_input_saved.png"))
                
                # Lock the attendance log of this staff
                page.click("text=Lock")
                page.wait_for_timeout(1000)
                
                # Verify it is locked (input should be disabled)
                is_disabled = page.eval_on_selector(att_input_selector, "el => el.disabled")
                if is_disabled:
                    if show:
                        print("Lock validation: Input successfully disabled.")
                else:
                    raise Exception("Failure: Attendance input was not disabled after lock.")
                    
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat5_attendance_locked.png"))
                    print("=> UAT 5 Attendance Logs & Lock: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 6: Reference Numbers Management
            # -----------------------------------------------------------------
            run, show = should_run_and_show(6)
            if run:
                if show:
                    print("\n[UAT 6] Managing Contract Reference Numbers...")
                page.goto(f"{base_url}/contracts/references")
                
                # Fill the Reference/Work Order Number for Contract 1 in month 2026-01
                ref_input_selector = "input.ref-input[data-contract-id='1'][data-month='2026-01']"
                page.wait_for_selector(ref_input_selector)
                page.fill(ref_input_selector, "WO-UAT-9999")
                
                # Shift focus to trigger auto-save
                page.press(ref_input_selector, "Tab")
                page.wait_for_timeout(1000)
                
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat6_reference_numbers.png"))
                    print("=> UAT 6 Reference Numbers Management: PASSED")
            
            # -----------------------------------------------------------------
            # UAT 7: XML Invoice Upload & Match
            # -----------------------------------------------------------------
            run, show = should_run_and_show(7)
            if run:
                if show:
                    print("\n[UAT 7] Uploading XML Invoice and Verifying Contract Match...")
                page.goto(f"{base_url}/invoice/new")
                
                # Upload XML file
                page.locator("input[name='xml_files']").set_input_files(str(PLAYWRIGHT_DIR / "mock_invoice.xml"))
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat7_invoice_selected.png"))
                
                # Click Import Invoice
                page.click("button:has-text('Import Invoice')")
                page.wait_for_timeout(2000)
                
                # Wait for Import Results page
                page.wait_for_selector("text=Import Results")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat7_import_results.png"))
                
                # Go back to Invoices List
                page.click("text=Invoices List")
                page.wait_for_timeout(2000)
                
                # Verify the invoice matched with MHB/FPT/UAT/001 framework contract
                page.wait_for_selector("text=Match")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat7_invoice_upload_match_success.png"))
                    print("=> UAT 7 XML Invoice Upload & Match: PASSED")

             # -----------------------------------------------------------------
            # UAT 8: Create a Vendor (Seller)
            # -----------------------------------------------------------------
            run, show = should_run_and_show(8)
            if run:
                if show:
                    print("\n[UAT 8] Creating a new Vendor (Seller)...")
                page.goto(f"{base_url}/vendor/new")
                page.fill("input[name='short_name']", "FPT2")
                page.fill("input[name='company_name_vi']", "FPT Software 2")
                page.fill("input[name='tax_id']", "0102135934-2")
                page.select_option("select[name='purchasing']", value="0")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat8_new_vendor_seller.png"))
                page.click("button[type='submit']")
                page.goto(f"{base_url}/vendors")
                page.wait_for_selector("text=FPT Software 2")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat8_vendor_list_success.png"))
                    print("=> UAT 8 Create Vendor (Seller): PASSED")

            # -----------------------------------------------------------------
            # UAT 9: Create a Vendor (Buyer)
            # -----------------------------------------------------------------
            run, show = should_run_and_show(9)
            if run:
                if show:
                    print("\n[UAT 9] Creating a new Vendor (Buyer)...")
                page.goto(f"{base_url}/vendor/new")
                page.fill("input[name='short_name']", "Mizuho2")
                page.fill("input[name='company_name_vi']", "Mizuho Bank 2")
                page.fill("input[name='tax_id']", "0100234567-2")
                page.select_option("select[name='purchasing']", value="1")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat9_new_vendor_buyer.png"))
                page.click("button[type='submit']")
                page.goto(f"{base_url}/vendors")
                page.wait_for_selector("text=Mizuho Bank 2")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat9_vendor_list_success.png"))
                    print("=> UAT 9 Create Vendor (Buyer): PASSED")

            # -----------------------------------------------------------------
            # UAT 10: Vendor Deactivation & Restoration
            # -----------------------------------------------------------------
            run, show = should_run_and_show(10)
            if run:
                if show:
                    print("\n[UAT 10] Deactivating and Restoring a Vendor...")
                page.goto(f"{base_url}/vendors")
                page.wait_for_selector("text=Mizuho Bank 2")
                page.wait_for_timeout(1000)
                page.click("tr:has-text('Mizuho Bank 2') button:has-text('Deactive')")
                page.wait_for_timeout(2000)
                
                page.goto(f"{base_url}/vendors?status=deactive")
                page.wait_for_selector("text=Mizuho Bank 2")
                page.click("tr:has-text('Mizuho Bank 2') button:has-text('Restore')")
                page.wait_for_timeout(2000)
                
                page.goto(f"{base_url}/vendors")
                page.wait_for_selector("text=Mizuho Bank 2")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat10_restored_success.png"))
                    print("=> UAT 10 Vendor Deactivation & Restoration: PASSED")

            # -----------------------------------------------------------------
            # UAT 11: Edit Staff Information
            # -----------------------------------------------------------------
            run, show = should_run_and_show(11)
            if run:
                if show:
                    print("\n[UAT 11] Editing Staff Information...")
                page.goto(f"{base_url}/staff/edit?id=1")
                page.fill("input[name='position']", "Principal QA Automator")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat11_editing_staff.png"))
                page.click("button[type='submit']")
                page.goto(f"{base_url}/staff")
                page.wait_for_selector("text=Principal QA Automator")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat11_staff_edit_success.png"))
                    print("=> UAT 11 Edit Staff Information: PASSED")

            # -----------------------------------------------------------------
            # UAT 12: Staff Deactivation & List Filter
            # -----------------------------------------------------------------
            run, show = should_run_and_show(12)
            if run:
                if show:
                    print("\n[UAT 12] Deactivating a Staff member...")
                page.goto(f"{base_url}/staff/new")
                page.fill("input[name='full_name_vi']", "Staff to Deactivate")
                page.select_option("select[name='vendor_id']", value="2")
                page.fill("input[name='position']", "Temp QA")
                page.click("button[type='submit']")
                page.wait_for_selector("text=Staff to Deactivate")
                
                page.click("tr:has-text('Staff to Deactivate') a:has-text('Edit')")
                page.wait_for_selector("select[name='status']")
                page.select_option("select[name='status']", value="inactive")
                page.click("button[type='submit']")
                
                page.goto(f"{base_url}/staff?status=active")
                page.wait_for_timeout(1000)
                assert page.locator("text=Staff to Deactivate").count() == 0
                
                page.goto(f"{base_url}/staff?status=inactive")
                page.wait_for_selector("text=Staff to Deactivate")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat12_inactive_staff_success.png"))
                    print("=> UAT 12 Staff Deactivation & Filter: PASSED")
                
                # Reactivate staff so that they can be used in UAT 23 and 24
                page.click("tr:has-text('Staff to Deactivate') a:has-text('Edit')")
                page.wait_for_selector("select[name='status']")
                page.select_option("select[name='status']", value="")
                page.click("button[type='submit']")
                
                # Allocate them to Contract 1, Annex 1 so that they are eligible for project assignments
                page.goto(f"{base_url}/contract/assign-staff?contract_id=1&annex_id=1")
                page.select_option("select[name='staff_id']", value="2")
                page.fill("input[name='joining_date']", "2026-01-01")
                page.fill("input[name='tentative_leaving_date']", "2026-06-30")
                page.fill("input[name='monthly_rate']", "45000000")
                page.click("button[type='submit']")

            # -----------------------------------------------------------------
            # UAT 13: Search & Filter Staff
            # -----------------------------------------------------------------
            run, show = should_run_and_show(13)
            if run:
                if show:
                    print("\n[UAT 13] Searching and Filtering Staff...")
                page.goto(f"{base_url}/staff")
                page.fill("input[name='q']", "Principal")
                page.press("input[name='q']", "Enter")
                page.wait_for_selector("text=Nguyen UAT Tester")
                assert page.locator("text=Staff to Deactivate").count() == 0
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat13_search_filter_success.png"))
                    print("=> UAT 13 Search & Filter Staff: PASSED")

            # -----------------------------------------------------------------
            # UAT 14: Contract Edit & Update
            # -----------------------------------------------------------------
            run, show = should_run_and_show(14)
            if run:
                if show:
                    print("\n[UAT 14] Editing Framework Contract...")
                page.goto(f"{base_url}/contract/edit?id=1")
                page.fill("input[name='end_date']", "2026-11-30")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat14_edit_contract.png"))
                page.click("button[type='submit']")
                
                page.goto(f"{base_url}/contract/edit?id=1")
                page.wait_for_selector("input[name='end_date'][value='2026-11-30']")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat14_contract_update_success.png"))
                    print("=> UAT 14 Contract Edit & Update: PASSED")

            # -----------------------------------------------------------------
            # UAT 15: Contract Deactivation & Restoration
            # -----------------------------------------------------------------
            run, show = should_run_and_show(15)
            if run:
                if show:
                    print("\n[UAT 15] Deactivating and Restoring Contract...")
                page.goto(f"{base_url}/contracts")
                page.wait_for_selector("text=MHB/FPT/UAT/001")
                page.wait_for_timeout(1000)
                page.click("tr:has-text('MHB/FPT/UAT/001') button:has-text('Delete')")
                page.wait_for_timeout(2000)
                
                page.goto(f"{base_url}/contracts?status=deleted")
                page.wait_for_selector("text=MHB/FPT/UAT/001")
                
                page.click("tr:has-text('MHB/FPT/UAT/001') button:has-text('Restore')")
                page.wait_for_timeout(2000)
                page.goto(f"{base_url}/contracts")
                page.wait_for_selector("text=MHB/FPT/UAT/001")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat15_contract_restore_success.png"))
                    print("=> UAT 15 Contract Deactivation & Restoration: PASSED")

            # -----------------------------------------------------------------
            # UAT 16: Create Annex with Value validation
            # -----------------------------------------------------------------
            run, show = should_run_and_show(16)
            if run:
                if show:
                    print("\n[UAT 16] Creating Annex with Value validation...")
                page.goto(f"{base_url}/annex/new?contract_id=1")
                page.fill("input[name='annex_name']", "Annex UAT 2026-B")
                page.fill("input[name='start_date']", "2026-07-01")
                page.fill("input[name='end_date']", "2026-12-31")
                page.fill("input[name='value']", "150000000")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat16_new_annex_filled.png"))
                page.click("button[type='submit']")
                page.wait_for_selector("text=Annex UAT 2026-B")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat16_annex_list_success.png"))
                    print("=> UAT 16 Create Annex with Value: PASSED")

            # -----------------------------------------------------------------
            # UAT 17: Annex Deactivation & Restoration
            # -----------------------------------------------------------------
            run, show = should_run_and_show(17)
            if run:
                if show:
                    print("\n[UAT 17] Deactivating and Restoring Annex...")
                page.goto(f"{base_url}/contract/edit?id=1")
                page.wait_for_selector("text=Annex UAT 2026-B")
                page.wait_for_timeout(1000)
                page.click("tr:has-text('Annex UAT 2026-B') button:has-text('Delete')")
                page.wait_for_timeout(2000)
                page.click("tr:has-text('Annex UAT 2026-B') button:has-text('Restore')")
                page.wait_for_timeout(2000)
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat17_annex_deactivate_restore_success.png"))
                    print("=> UAT 17 Annex Deactivation & Restoration: PASSED")

            # -----------------------------------------------------------------
            # UAT 18: Staff Allocation Overlap Validation
            # -----------------------------------------------------------------
            run, show = should_run_and_show(18)
            if run:
                if show:
                    print("\n[UAT 18] Testing Staff Allocation Overlap Validation...")
                page.goto(f"{base_url}/contract/assign-staff?contract_id=1&annex_id=2")
                page.select_option("select[name='staff_id']", value="1")
                page.fill("input[name='joining_date']", "2026-01-15")
                page.fill("input[name='tentative_leaving_date']", "2026-03-31")
                page.fill("input[name='monthly_rate']", "60000000")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat18_overlap_submission.png"))
                page.click("button[type='submit']")
                
                page.wait_for_selector("text=overlap")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat18_overlap_error_displayed.png"))
                    print("=> UAT 18 Staff Allocation Overlap Validation: PASSED")

            # -----------------------------------------------------------------
            # UAT 19: Staff Allocation Rates Update
            # -----------------------------------------------------------------
            run, show = should_run_and_show(19)
            if run:
                if show:
                    print("\n[UAT 19] Updating Staff Allocation Rates...")
                page.goto(f"{base_url}/contract/edit-staff-link?id=1")
                page.fill("input[name='monthly_rate']", "60000000")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat19_updating_rates.png"))
                page.click("button[type='submit']")
                page.wait_for_selector("text=60,000,000")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat19_rates_update_success.png"))
                    print("=> UAT 19 Staff Allocation Rates Update: PASSED")

            # -----------------------------------------------------------------
            # UAT 20: Remove Staff Allocation
            # -----------------------------------------------------------------
            run, show = should_run_and_show(20)
            if run:
                if show:
                    print("\n[UAT 20] Removing a Staff Allocation...")
                page.goto(f"{base_url}/staff/new")
                page.fill("input[name='full_name_vi']", "Staff to Remove Alloc")
                page.select_option("select[name='vendor_id']", value="2")
                page.click("button[type='submit']")
                
                page.goto(f"{base_url}/contract/assign-staff?contract_id=1&annex_id=1")
                page.eval_on_selector("select[name='staff_id']", """
                    select => {
                        for (let i = 0; i < select.options.length; i++) {
                            if (select.options[i].text.includes("Staff to Remove Alloc")) {
                                select.selectedIndex = i;
                                select.dispatchEvent(new Event('change'));
                                break;
                            }
                        }
                    }
                """)
                page.fill("input[name='joining_date']", "2026-05-01")
                page.click("button[type='submit']")
                
                page.goto(f"{base_url}/contract/edit?id=1")
                page.locator("span", has_text="Staff to Remove Alloc").locator("..").locator("button", has_text="Remove").click()
                page.wait_for_selector("text=Staff to Remove Alloc", state="detached")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat20_remove_allocation_success.png"))
                    print("=> UAT 20 Remove Staff Allocation: PASSED")

            # -----------------------------------------------------------------
            # UAT 21: Create a Project
            # -----------------------------------------------------------------
            run, show = should_run_and_show(21)
            if run:
                if show:
                    print("\n[UAT 21] Creating a new Project...")
                page.goto(f"{base_url}/projects")
                page.fill("input[name='short_name']", "UAT_PROJ")
                page.fill("input[name='full_name']", "UAT Test Project")
                page.fill("input[name='it_outsourcing_budget']", "500000000")
                page.fill("input[name='os_start_date']", "2026-01-01")
                page.fill("input[name='os_end_date']", "2026-12-31")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat21_new_project_filled.png"))
                page.click("button[type='submit']")
                page.wait_for_selector("text=UAT_PROJ")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat21_project_list_success.png"))
                    print("=> UAT 21 Create Project: PASSED")

            # -----------------------------------------------------------------
            # UAT 22: Project Close & Reopen
            # -----------------------------------------------------------------
            run, show = should_run_and_show(22)
            if run:
                if show:
                    print("\n[UAT 22] Closing and Reopening a Project...")
                page.goto(f"{base_url}/projects")
                page.click("tr:has-text('UAT_PROJ') button:has-text('Close')")
                page.wait_for_timeout(1000)
                page.click("tr:has-text('UAT_PROJ') button:has-text('Reopen')")
                page.wait_for_timeout(1000)
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat22_project_close_reopen_success.png"))
                    print("=> UAT 22 Project Close & Reopen: PASSED")

            # -----------------------------------------------------------------
            # UAT 23: Assign Staff to Project via Dropdown
            # -----------------------------------------------------------------
            run, show = should_run_and_show(23)
            if run:
                if show:
                    print("\n[UAT 23] Assigning Staff to Project via Dropdown...")
                page.goto(f"{base_url}/projects/assign?project_id=1")
                page.select_option("select[id='add_staff_select']", value="2")
                page.check("input[name='months'][value='2026-01']")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat23_assign_dropdown.png"))
                page.click("button:has-text('Add Staff to Project')")
                page.wait_for_selector("text=Staff to Deactivate")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat23_assigned_success.png"))
                    print("=> UAT 23 Assign Staff via Dropdown: PASSED")

            # -----------------------------------------------------------------
            # UAT 24: Unassign Staff from Project via Matrix
            # -----------------------------------------------------------------
            run, show = should_run_and_show(24)
            if run:
                if show:
                    print("\n[UAT 24] Unassigning Staff from Project via Matrix...")
                page.goto(f"{base_url}/staff/edit?id=2")
                checkbox_selector = "input[data-project-id='1'][data-month='2026-01']"
                page.wait_for_selector(checkbox_selector)
                page.uncheck(checkbox_selector)
                page.wait_for_timeout(1500)
                # After unassigning, Project 1 disappears from matrix because there are no more assignments to it.
                assert page.locator(checkbox_selector).count() == 0
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat24_unassigned_matrix_success.png"))
                    print("=> UAT 24 Unassign Staff via Matrix: PASSED")

            # -----------------------------------------------------------------
            # UAT 25: Attendance Log cell validation (Invalid format input)
            # -----------------------------------------------------------------
            run, show = should_run_and_show(25)
            if run:
                if show:
                    print("\n[UAT 25] Testing Attendance Log cell validation (Invalid input)...")
                page.goto(f"{base_url}/attendance?month=2026-02")
                att_input_selector = "input[name='w_1_2026-02-01']"
                page.wait_for_selector(att_input_selector)
                page.eval_on_selector(att_input_selector, "el => { el.value = 'invalid_hours'; el.dispatchEvent(new Event('change')); }")
                page.wait_for_timeout(1000)
                curr_val = page.eval_on_selector(att_input_selector, "el => el.value")
                assert curr_val != "invalid_hours"
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat25_validation_success.png"))
                    print("=> UAT 25 Attendance Log Cell Validation: PASSED")

            # -----------------------------------------------------------------
            # UAT 26: Unlock Attendance Log
            # -----------------------------------------------------------------
            run, show = should_run_and_show(26)
            if run:
                if show:
                    print("\n[UAT 26] Unlocking Attendance Log...")
                page.goto(f"{base_url}/attendance?month=2026-01")
                page.click("text=Unlock")
                page.wait_for_timeout(1000)
                att_input_selector = "input[name='w_1_2026-01-01']"
                is_disabled = page.eval_on_selector(att_input_selector, "el => el.disabled")
                assert not is_disabled
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat26_unlock_success.png"))
                    print("=> UAT 26 Unlock Attendance Log: PASSED")

            # -----------------------------------------------------------------
            # UAT 27: Audit Logs Search & Verification
            # -----------------------------------------------------------------
            run, show = should_run_and_show(27)
            if run:
                if show:
                    print("\n[UAT 27] Verifying Audit Logs...")
                page.goto(f"{base_url}/audit-logs")
                page.fill("input[name='search']", "Nguyen UAT Tester")
                page.press("input[name='search']", "Enter")
                page.wait_for_selector("td:has-text('CREATE_STAFF')")
                page.wait_for_selector("td:has-text('Nguyen UAT Tester')")
                if show:
                    page.screenshot(path=str(SCREENSHOTS_DIR / "uat27_audit_logs_success.png"))
                    print("=> UAT 27 Audit Logs Search & Verification: PASSED")

            # -----------------------------------------------------------------
            # UAT Results Summary
            # -----------------------------------------------------------------
            print("\n" + "="*70)
            if target_tc is None:
                print("  CONGRATULATIONS: ALL UAT AUTOMATION SCENARIOS PASSED! 🎉")
            else:
                print(f"  CONGRATULATIONS: UAT SCENARIO {target_tc} PASSED! 🎉")
            print(f"  Screenshots folder: {SCREENSHOTS_DIR}")
            print("="*70 + "\n")
            
        except Exception as e:
            print("\n" + "!"*70)
            print(f"UAT SCENARIO FAILED: {e}")
            import traceback
            traceback.print_exc()
            page.screenshot(path=str(SCREENSHOTS_DIR / "uat_failure.png"))
            print("!"*70 + "\n")
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    # Check if we should write logs to file
    log_file_handle = None
    if "--log-to-file" in sys.argv:
        log_path = PLAYWRIGHT_DIR / "run_progress.log"
        log_file_handle = open(log_path, "a", buffering=1)
        sys.stdout = log_file_handle
        sys.stderr = log_file_handle

    check_dependencies()
    init_uat_db()
    
    server_process = None
    log_file = None
    try:
        server_process, log_file = start_server()
        run_playwright_tests()
    finally:
        if server_process:
            print("Stopping UAT local server...")
            server_process.terminate()
            server_process.wait()
            print("Server stopped.")
        if log_file:
            log_file.close()
        if log_file_handle:
            log_file_handle.close()
