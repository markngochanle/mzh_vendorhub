import os
from playwright.sync_api import sync_playwright

html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Mizuho VMS - Executive Infographic & System Overview</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

    @page {
      size: A4 portrait;
      margin: 10mm 12mm 10mm 12mm;
    }

    * {
      box-sizing: border-box;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }

    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 0;
      background: #ffffff;
      color: #0f172a;
      font-size: 11px;
      line-height: 1.45;
    }

    .page {
      width: 100%;
      min-height: 275mm;
      max-height: 277mm;
      page-break-after: always;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      overflow: hidden;
    }

    .page:last-child {
      page-break-after: avoid;
    }

    /* Header Banner */
    .header-banner {
      background: linear-gradient(135deg, #183181 0%, #0f1f54 100%);
      color: #ffffff;
      border-radius: 8px;
      padding: 16px 20px;
      position: relative;
      border-bottom: 4px solid #ed1a3a;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      box-shadow: 0 4px 12px rgba(24, 49, 129, 0.15);
    }

    .header-title-group h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 800;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 10px;
      color: #ffffff;
    }

    .header-title-group h1 span.badge {
      background: #ed1a3a;
      color: #ffffff;
      font-size: 10px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }

    .header-subtitle {
      margin: 4px 0 0 0;
      font-size: 11px;
      color: #cbd5e1;
      font-weight: 400;
    }

    .header-meta {
      text-align: right;
      font-size: 10px;
      color: #94a3b8;
    }

    .header-meta strong {
      color: #ffffff;
      display: block;
      font-size: 11px;
    }

    /* KPI Highlights Ribbon */
    .kpi-ribbon {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 12px;
    }

    .kpi-card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 10px 12px;
      text-align: center;
      position: relative;
      overflow: hidden;
    }

    .kpi-card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
    }

    .kpi-card.blue::before { background: #183181; }
    .kpi-card.green::before { background: #10b981; }
    .kpi-card.purple::before { background: #6366f1; }
    .kpi-card.red::before { background: #ed1a3a; }

    .kpi-val {
      font-size: 18px;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.1;
      margin-bottom: 2px;
    }

    .kpi-lbl {
      font-size: 9.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: #64748b;
    }

    .kpi-desc {
      font-size: 8.5px;
      color: #475569;
      margin-top: 3px;
    }

    /* Visual Process Flow */
    .process-section {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 12px;
    }

    .section-title {
      font-size: 12px;
      font-weight: 800;
      color: #183181;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin: 0 0 8px 0;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .process-flow {
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 6px;
      position: relative;
    }

    .flow-step {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px 6px;
      text-align: center;
      position: relative;
    }

    .flow-step.active {
      background: #eff6ff;
      border-color: #bfdbfe;
    }

    .step-num {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #183181;
      color: #ffffff;
      font-size: 9px;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 4px auto;
    }

    .step-title {
      font-size: 9.5px;
      font-weight: 700;
      color: #0f172a;
      line-height: 1.2;
      margin-bottom: 2px;
    }

    .step-desc {
      font-size: 8px;
      color: #64748b;
      line-height: 1.2;
    }

    /* 2-Column Core Architecture Grid */
    .grid-2col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 10px;
    }

    .card-block {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .card-block-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #f1f5f9;
      padding-bottom: 4px;
      margin-bottom: 2px;
    }

    .card-block-title {
      font-size: 11px;
      font-weight: 700;
      color: #183181;
      display: flex;
      align-items: center;
      gap: 5px;
    }

    .card-block-tag {
      font-size: 8px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 3px;
      text-transform: uppercase;
      background: #f1f5f9;
      color: #475569;
    }

    .tag-blue { background: #dbeafe; color: #1e40af; }
    .tag-green { background: #dcfce7; color: #15803d; }
    .tag-purple { background: #ede9fe; color: #6b21a8; }
    .tag-red { background: #fee2e2; color: #991b1b; }
    .tag-amber { background: #fef3c7; color: #b45309; }

    .bullet-list {
      margin: 0;
      padding-left: 14px;
      font-size: 9.5px;
      color: #334155;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .bullet-list li strong {
      color: #0f172a;
    }

    /* Visual Feature Demonstration Mockups */
    .mini-mockup {
      background: #f8fafc;
      border: 1px dashed #cbd5e1;
      border-radius: 4px;
      padding: 6px 8px;
      margin-top: 4px;
      font-size: 9px;
    }

    /* Punctuality Matrix Visual Legend */
    .matrix-legend-row {
      display: flex;
      gap: 8px;
      align-items: center;
      margin-top: 4px;
    }

    .matrix-cell-sample {
      width: 18px;
      height: 18px;
      border-radius: 3px;
      border: 1px solid #94a3b8;
      display: inline-block;
      position: relative;
    }

    .cell-ontime { background: #ffffff; }
    .cell-absent { background: #cbd5e1; }
    .cell-split-yellow {
      background: linear-gradient(135deg, #facc15 50%, #ffffff 50%);
    }
    .cell-split-red {
      background: linear-gradient(135deg, #ffffff 50%, #ef4444 50%);
    }
    .cell-split-both {
      background: linear-gradient(135deg, #facc15 50%, #ef4444 50%);
    }

    /* Modern Table Style */
    .infographic-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 9px;
      margin-top: 6px;
    }

    .infographic-table th {
      background: #183181;
      color: #ffffff;
      font-weight: 700;
      text-align: left;
      padding: 5px 8px;
      border: 1px solid #183181;
    }

    .infographic-table td {
      padding: 5px 8px;
      border: 1px solid #e2e8f0;
      color: #334155;
    }

    .infographic-table tr:nth-child(even) td {
      background: #f8fafc;
    }

    /* Page Footer */
    .footer-bar {
      border-top: 1px solid #e2e8f0;
      padding-top: 6px;
      margin-top: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 8.5px;
      color: #94a3b8;
    }

    .footer-bar strong {
      color: #183181;
    }

    /* Badge Pills */
    .pill {
      display: inline-flex;
      align-items: center;
      padding: 1px 6px;
      border-radius: 999px;
      font-size: 8px;
      font-weight: 700;
    }

    .pill-green { background: #dcfce7; color: #166534; }
    .pill-amber { background: #fef3c7; color: #92400e; }
    .pill-red { background: #fee2e2; color: #991b1b; }
    .pill-blue { background: #dbeafe; color: #1e40af; }
  </style>
</head>
<body>

  <!-- ==================== PAGE 1 ==================== -->
  <div class="page">
    <div>
      <!-- Header Banner -->
      <div class="header-banner">
        <div class="header-title-group">
          <h1>
            MIZUHO VMS
            <span class="badge">Enterprise Solution</span>
          </h1>
          <div class="header-subtitle">
            Vendor &amp; External Workforce Management System | Mizuho Bank Vietnam IT Division
          </div>
        </div>
        <div class="header-meta">
          <strong>CONFIDENTIAL // FOR INTERNAL USE</strong>
          <span>Architecture &amp; Functional Capabilities Brief</span>
        </div>
      </div>

      <!-- KPI Highlights Ribbon -->
      <div class="kpi-ribbon">
        <div class="kpi-card blue">
          <div class="kpi-val">100%</div>
          <div class="kpi-lbl">Annex Coverage Mandate</div>
          <div class="kpi-desc">Strict legal protection for every deployed contractor</div>
        </div>
        <div class="kpi-card green">
          <div class="kpi-val">3-Way</div>
          <div class="kpi-lbl">Auto Reconciliation</div>
          <div class="kpi-desc">E-Invoice XML ⟷ Contract ⟷ Payroll Timesheet</div>
        </div>
        <div class="kpi-card purple">
          <div class="kpi-val">3 Models</div>
          <div class="kpi-lbl">Spend Architecture</div>
          <div class="kpi-desc">Time &amp; Material (T&amp;M), Fixed Price &amp; Recurring</div>
        </div>
        <div class="kpi-card red">
          <div class="kpi-val">Air-Gapped</div>
          <div class="kpi-lbl">Bank-Grade Security</div>
          <div class="kpi-desc">Zero cloud dependency; 100% on-premise audit trail</div>
        </div>
      </div>

      <!-- End-to-End Operational Flow -->
      <div class="process-section">
        <div class="section-title">
          <span>🔄</span> End-to-End Vendor Governance &amp; Financial Lifecycle Flow
        </div>
        <div class="process-flow">
          <div class="flow-step">
            <div class="step-num">1</div>
            <div class="step-title">Contract &amp; Annex</div>
            <div class="step-desc">Establish master agreements &amp; budget caps</div>
          </div>
          <div class="flow-step">
            <div class="step-num">2</div>
            <div class="step-title">Resource Allocation</div>
            <div class="step-desc">Onboard staff with shift rules &amp; project matrix</div>
          </div>
          <div class="flow-step">
            <div class="step-num">3</div>
            <div class="step-title">Attendance Tracking</div>
            <div class="step-desc">Daily punches &amp; visual punctuality matrix</div>
          </div>
          <div class="flow-step">
            <div class="step-num">4</div>
            <div class="step-title">Payroll &amp; Acceptance</div>
            <div class="step-desc">Monthly lock, rate computation &amp; sign-off</div>
          </div>
          <div class="flow-step">
            <div class="step-num">5</div>
            <div class="step-title">Invoice 3-Way Match</div>
            <div class="step-desc">XML parsing &amp; automated 4-tier recon</div>
          </div>
          <div class="flow-step active">
            <div class="step-num">6</div>
            <div class="step-title">MGS &amp; Cash-Out</div>
            <div class="step-desc">Payment execution &amp; Fiscal Year tracking</div>
          </div>
        </div>
      </div>

      <!-- Core Capabilities Grid (Top 4 Pillars) -->
      <div class="grid-2col">
        
        <!-- Pillar 1: Contract Lifecycle -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>📜</span> 1. Contract &amp; Renewal Engine
            </div>
            <span class="card-block-tag tag-blue">Lifecycle Governance</span>
          </div>
          <ul class="bullet-list">
            <li><strong>Hierarchical Structure:</strong> Master Framework Contracts linked to granular Contract Annexes with discrete monetary values and validity periods.</li>
            <li><strong>Automated Renewal Policies:</strong> Standalone contracts support <code>AUTO-RENEW</code>, <code>MANUAL-RENEW</code>, and <code>NON-RENEWABLE</code> modes.</li>
            <li><strong>Proactive Notice Windows:</strong> Configurable notice window (e.g. 60 or 30 days) triggers early alerts on the executive dashboard to prevent service interruptions.</li>
            <li><strong>Reference Codes:</strong> Integrated payment reference code repository with automated tracking of sent MGS requests.</li>
          </ul>
          <div class="mini-mockup">
            <span class="pill pill-green">Auto-Renew (12M)</span>
            <span class="pill pill-amber">Manual-Renew (Notice 60d)</span>
            <span class="pill pill-blue">Annex Coverage Valid</span>
          </div>
        </div>

        <!-- Pillar 2: Workforce Governance -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>👥</span> 2. Workforce Governance &amp; Allocation
            </div>
            <span class="card-block-tag tag-green">Resource Control</span>
          </div>
          <ul class="bullet-list">
            <li><strong>Strict Annex Mandate:</strong> Enforces that zero external contractors can be billed or logged without an active contract annex.</li>
            <li><strong>Multi-Project Matrix:</strong> Dynamic matrix allocating staff across concurrent Mizuho IT projects with fractional percentage weightings.</li>
            <li><strong>Shift Schedules:</strong> Configurable per-staff working hours (e.g., <code>08:00 - 17:00</code> or <code>08:30 - 17:30</code>) governing punctuality benchmarks.</li>
            <li><strong>Leave &amp; OT Rules:</strong> Comprehensive paid leave balance tracking and standardized Overtime (OT) conversion factors.</li>
          </ul>
          <div class="mini-mockup">
            <strong>Allocation Rule:</strong> Staff ➔ Active Annex (100%) ➔ Project A (60%) + Project B (40%)
          </div>
        </div>

        <!-- Pillar 3: Punctuality Matrix -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>⏱️</span> 3. Actual Punctuality &amp; Timesheet Matrix
            </div>
            <span class="card-block-tag tag-amber">Discipline Analytics</span>
          </div>
          <ul class="bullet-list">
            <li><strong>2D Diagonal-Split Visualization:</strong> Patented visual matrix representing each staff day as a square with dual diagonal status rendering:</li>
            <div class="matrix-legend-row">
              <span class="matrix-cell-sample cell-ontime" title="Full White: On-Time"></span> <span style="font-size:8px;">On-Time</span>
              <span class="matrix-cell-sample cell-split-yellow" title="Yellow Top: Late In"></span> <span style="font-size:8px;">Late In</span>
              <span class="matrix-cell-sample cell-split-red" title="Red Bottom: Early Out"></span> <span style="font-size:8px;">Early Out</span>
              <span class="matrix-cell-sample cell-split-both" title="Both Late & Early"></span> <span style="font-size:8px;">Both</span>
              <span class="matrix-cell-sample cell-absent" title="Full Gray: Weekend/Absent"></span> <span style="font-size:8px;">Off</span>
            </div>
            <li><strong>Real-Time Thresholds:</strong> Dynamic computation against individual work shifts; hover tooltips expose exact punch timestamps.</li>
            <li><strong>Cryptographic Data Lock:</strong> One-click lock freezes monthly punch logs to prevent post-audit tampering before payroll calculation.</li>
          </ul>
        </div>

        <!-- Pillar 4: Invoice Reconciliation -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>🧾</span> 4. 3-Way E-Invoice Auto Reconciliation
            </div>
            <span class="card-block-tag tag-purple">Financial Integrity</span>
          </div>
          <ul class="bullet-list">
            <li><strong>Decree 123/TT78 XML Parser:</strong> Direct ingest of vendor XML e-invoices with digital signature and tax metadata extraction.</li>
            <li><strong>Automated 4-Tier Matching:</strong> Instantly categorizes invoices into:
              <code>Matched</code> (100% exact), <code>Mismatch</code> (amount variance), <code>No Payroll</code>, or <code>No Contract</code>.</li>
            <li><strong>MGS Generator:</strong> Auto-populates Mizuho Global Services payment forms with one-click print-to-PDF and clipboard email body generation.</li>
          </ul>
          <div class="mini-mockup">
            <span class="pill pill-green">Matched: 100% OK</span>
            <span class="pill pill-blue">MGS Form Ready</span>
            <span class="pill pill-amber">VAT Tax Reconciled</span>
          </div>
        </div>

      </div>
    </div>

    <!-- Page 1 Footer -->
    <div class="footer-bar">
      <div><strong>Mizuho VMS</strong> // Enterprise IT Vendor &amp; Workforce Management Platform</div>
      <div>Page 1 of 2 // Executive Governance Brief</div>
    </div>
  </div>

  <!-- ==================== PAGE 2 ==================== -->
  <div class="page">
    <div>
      <!-- Header Banner -->
      <div class="header-banner" style="margin-bottom:10px;">
        <div class="header-title-group">
          <h1>
            FINANCIAL ARCHITECTURE &amp; AUDIT CONTROL
            <span class="badge">Multi-Model Governance</span>
          </h1>
          <div class="header-subtitle">
            Cash-Out Execution, Project Budget Health &amp; Enterprise Compliance
          </div>
        </div>
        <div class="header-meta">
          <strong>MIZUHO BANK VIETNAM</strong>
          <span>Fiscal Year (FY) Spend Governance</span>
        </div>
      </div>

      <!-- Multi-Model Spend Architecture -->
      <div class="process-section" style="margin-bottom:10px;">
        <div class="section-title">
          <span>💳</span> The 3 Pillars of Multi-Model Spend Architecture
        </div>
        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px;">
          
          <div class="kpi-card blue" style="text-align:left; padding:8px 10px;">
            <div style="font-size:11px; font-weight:800; color:#183181; margin-bottom:4px;">1. Time &amp; Material (T&amp;M)</div>
            <div style="font-size:8.5px; color:#334155; line-height:1.35;">
              • Billed on validated daily hours &amp; daily rates.<br>
              • Monthly formula: <code>(Standard Days + Actual Days + Approved Leave) × Daily Rate + OT</code>.<br>
              • Formal Acceptance Certificate generated upon sign-off.
            </div>
          </div>

          <div class="kpi-card purple" style="text-align:left; padding:8px 10px;">
            <div style="font-size:11px; font-weight:800; color:#6366f1; margin-bottom:4px;">2. Fixed Price Milestones</div>
            <div style="font-size:8.5px; color:#334155; line-height:1.35;">
              • Structured milestone disbursement stages: Advance, Delivery, Acceptance, Warranty.<br>
              • Acceptance document tracking &amp; percentage completion validation.<br>
              • Linked directly to milestone invoices.
            </div>
          </div>

          <div class="kpi-card green" style="text-align:left; padding:8px 10px;">
            <div style="font-size:11px; font-weight:800; color:#10b981; margin-bottom:4px;">3. Recurring Services</div>
            <div style="font-size:8.5px; color:#334155; line-height:1.35;">
              • Fixed monthly IT subscriptions: Leased lines, Cloud SaaS licenses, IT hardware maintenance.<br>
              • Automatic monthly disbursement schedule.<br>
              • Notice window contract expiration alerts.
            </div>
          </div>

        </div>
      </div>

      <!-- Fiscal Year Cash-Out Execution & Budget Burn Rate -->
      <div class="grid-2col">
        
        <!-- Cash-Out Execution -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>🏦</span> Fiscal Year Cash-Out Execution
            </div>
            <span class="card-block-tag tag-green">Actual Disbursement</span>
          </div>
          <div style="font-size:9.5px; color:#334155; line-height:1.4;">
            Mizuho VMS distinguishes between <strong>Accounting Incurred Cost</strong> and <strong>Executed Cash-Out (Actual Bank Disbursement)</strong>:
          </div>
          <ul class="bullet-list" style="margin-top:2px;">
            <li><strong>Fiscal Year Timeline:</strong> Structured strictly around Mizuho's financial calendar (April 1 to March 31).</li>
            <li><strong>Disbursement Date Tagging:</strong> Every T&amp;M annex, Fixed Price milestone, and Recurring service payout receives a verified <code>Cashout Date</code>.</li>
            <li><strong>Cross-Fiscal Reconciliation:</strong> Prevents uncashed liabilities from distorting current-year OPEX statements.</li>
          </ul>
          <div class="mini-mockup" style="font-family:'JetBrains Mono', monospace; font-size:8px;">
            FY Cycle: [Apr] ➔ [May] ➔ ... ➔ [Mar Year+1] // Tagged to Actual Cashout Date
          </div>
        </div>

        <!-- Project Budget Health -->
        <div class="card-block">
          <div class="card-block-header">
            <div class="card-block-title">
              <span>📊</span> Project Budget Burn-Rate Alerting
            </div>
            <span class="card-block-tag tag-amber">Overrun Protection</span>
          </div>
          <div style="font-size:9.5px; color:#334155; line-height:1.4;">
            Real-time telemetry across internal Mizuho IT projects prevents budget overruns before commitments are executed:
          </div>
          <table class="infographic-table" style="margin-top:4px;">
            <thead>
              <tr>
                <th>Burn-Rate</th>
                <th>Status Badge</th>
                <th>System Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>&lt; 75%</td>
                <td><span class="pill pill-green">Healthy</span></td>
                <td>Standard automated approvals</td>
              </tr>
              <tr>
                <td>75% - 90%</td>
                <td><span class="pill pill-amber">Warning (&gt;75%)</span></td>
                <td>Flagged on Executive Dashboard</td>
              </tr>
              <tr>
                <td>90% - 100%</td>
                <td><span class="pill pill-red">Critical (&gt;90%)</span></td>
                <td>PMO notification triggered</td>
              </tr>
              <tr>
                <td>&gt; 100%</td>
                <td><span class="pill pill-red" style="font-weight:900;">Over Budget</span></td>
                <td>Allocation locks enforced</td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>

      <!-- Enterprise Compliance & Audit Assurance Table -->
      <div class="process-section" style="margin-bottom:10px;">
        <div class="section-title">
          <span>🛡️</span> Enterprise Governance, Audit Trail &amp; Architecture Standards
        </div>
        <table class="infographic-table">
          <thead>
            <tr>
              <th style="width:22%;">Governance Dimension</th>
              <th style="width:40%;">System Capability</th>
              <th style="width:38%;">Bank Value &amp; Compliance Impact</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Air-Gapped Standalone</strong></td>
              <td>100% zero external dependencies; bundled local Chart.js, jsPDF &amp; native CSS.</td>
              <td>Complies with Mizuho Information Security policies; immune to external CDN outages.</td>
            </tr>
            <tr>
              <td><strong>Immutable Audit Trail</strong></td>
              <td>Captures timestamp, operator IP, action, entity ID, and before/after state diffs.</td>
              <td>Provides tamper-proof logs for internal compliance, J-SOX, and external auditors.</td>
            </tr>
            <tr>
              <td><strong>Corporate Identity</strong></td>
              <td>Standardized on Mizuho Cosmic Blue (<code>#183181</code>) &amp; Accent Red (<code>#ed1a3a</code>).</td>
              <td>Unified enterprise branding across all navigation bars, cards, charts, and PDF exports.</td>
            </tr>
            <tr>
              <td><strong>Bilingual Architecture</strong></td>
              <td>English executive UI with full localized support for Vietnamese e-invoices and labor codes.</td>
              <td>Seamless alignment between local project teams and Tokyo regional stakeholders.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Strategic ROI Summary Card -->
      <div class="kpi-card" style="background:linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%); border-color:#bfdbfe; text-align:left; padding:10px 14px;">
        <div style="font-size:11px; font-weight:800; color:#183181; margin-bottom:4px; display:flex; align-items:center; gap:6px;">
          <span>🎯</span> Strategic Business Impact &amp; ROI for Mizuho Bank
        </div>
        <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; font-size:8.5px; color:#334155; margin-top:4px;">
          <div>
            <strong style="color:#10b981; font-size:11px; display:block;">90% Faster</strong>
            Reconciliation time reduced from days to seconds via automated XML matching.
          </div>
          <div>
            <strong style="color:#183181; font-size:11px; display:block;">100% Verified</strong>
            Zero uncontracted or unauthorized headcount allowed on bank premises.
          </div>
          <div>
            <strong style="color:#6366f1; font-size:11px; display:block;">Zero Leakage</strong>
            Cryptographic timesheet locks prevent post-approval rate or hour inflation.
          </div>
          <div>
            <strong style="color:#ed1a3a; font-size:11px; display:block;">Real-Time FY</strong>
            Continuous alignment between OPEX forecasts and bank cash-out reality.
          </div>
        </div>
      </div>

    </div>

    <!-- Page 2 Footer -->
    <div class="footer-bar">
      <div><strong>Mizuho VMS</strong> // Mizuho Bank Vietnam IT Outsourcing Governance</div>
      <div>Page 2 of 2 // Executive Governance Brief</div>
    </div>
  </div>

</body>
</html>
"""

# Write HTML file
html_path = "/Users/local/04.working/17.mizuho/vendor_management/Mizuho_VMS_Infographic.html"
pdf_path = "/Users/local/04.working/17.mizuho/vendor_management/Mizuho_VMS_Infographic.pdf"

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"HTML written to {html_path}")

# Render to PDF using Playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(f"file://{html_path}")
    page.wait_for_load_state("networkidle")
    page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
    )
    browser.close()

print(f"PDF successfully generated at {pdf_path}")
