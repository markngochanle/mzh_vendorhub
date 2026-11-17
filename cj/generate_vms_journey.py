#!/usr/bin/env python3
"""
generate_vms_journey.py
Generates a multi-page executive Customer Journey Mapping diagram in Draw.io format (.drawio)
for Mizuho VMS (Vendor & Workforce Management System).

Page 1: End-to-End Big Picture Journey (Ngân sách đầu nguồn -> Vận hành -> Thực chi -> Tái ký)
Page 2: Deep-Dive: Attendance Punctuality Matrix & 3-Way E-Invoice Reconciliation Flow
"""

import html
import uuid

def gen_id():
    return str(uuid.uuid4()).replace("-", "")[:20]

def create_task_card(card_id, x, y, width, height, actor, task_text, system_text, actor_bg="#e2e8f0", stroke="#000000", parent_id="1"):
    actor_esc = html.escape(actor)
    task_esc = html.escape(task_text)
    system_esc = html.escape(system_text)
    
    header_h = 22
    footer_h = 24
    body_h = height - header_h - footer_h
    
    xml = f"""
    <!-- Task Container {card_id} -->
    <mxCell id="{card_id}" value="" style="rounded=1;whiteSpace=wrap;html=1;container=1;collapsible=0;absoluteArcSize=1;arcSize=14;childLayout=stackLayout;horizontal=1;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;fontSize=12;strokeColor={stroke};strokeWidth=1.5;shadow=1;" vertex="1" parent="{parent_id}">
      <mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry" />
    </mxCell>
    <mxCell id="{card_id}_h" value="&lt;b&gt;{actor_esc}&lt;/b&gt;" style="whiteSpace=wrap;connectable=0;html=1;shape=mxgraph.basic.rect;size=10;rectStyle=rounded;bottomRightStyle=square;bottomLeftStyle=square;part=1;rounded=1;fontSize=11;strokeColor={stroke};strokeWidth=1;fillColor={actor_bg};fontColor=#0f172a;" vertex="1" parent="{card_id}">
      <mxGeometry width="{width}" height="{header_h}" as="geometry" />
    </mxCell>
    <mxCell id="{card_id}_b" value="{task_esc}" style="shape=mxgraph.bpmn.task;part=1;taskMarker=abstract;connectable=0;whiteSpace=wrap;rounded=1;fontSize=11;strokeColor={stroke};strokeWidth=1;fillColor=#ffffff;fontColor=#1e293b;align=left;spacingLeft=8;spacingRight=8;" vertex="1" parent="{card_id}">
      <mxGeometry y="{header_h}" width="{width}" height="{body_h}" as="geometry" />
    </mxCell>
    <mxCell id="{card_id}_f" value="📱 {system_esc}" style="whiteSpace=wrap;connectable=0;html=1;shape=mxgraph.basic.rect;size=10;rectStyle=rounded;topRightStyle=square;topLeftStyle=square;fillColor=#f1f5f9;part=1;rounded=1;fontSize=10;strokeColor={stroke};strokeWidth=1;fontColor=#475569;fontStyle=2;" vertex="1" parent="{card_id}">
      <mxGeometry y="{header_h + body_h}" width="{width}" height="{footer_h}" as="geometry" />
    </mxCell>
    """
    return xml

def create_edge(edge_id, source_id, target_id, label="", stroke="#183181", stroke_width=2, parent_id="1"):
    label_esc = html.escape(label)
    return f"""
    <mxCell id="{edge_id}" value="{label_esc}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;fontSize=10;startArrow=none;startFill=0;endArrow=classic;endFill=1;strokeColor={stroke};strokeWidth={stroke_width};fontColor={stroke};" edge="1" parent="{parent_id}" source="{source_id}" target="{target_id}">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    """

def build_page_1():
    stages = [
        {"num": "1", "name": "Lập Kế hoạch & Ngân sách Đầu nguồn", "sub": "Upstream Budgeting & Cap Allocation", "x": 220, "w": 460},
        {"num": "2", "name": "Mua sắm & Ký kết Hợp đồng", "sub": "Vendor Sourcing & Contracts", "x": 700, "w": 460},
        {"num": "3", "name": "Tiếp nhận & Phân bổ Nguồn lực", "sub": "Resource Onboarding & Allocation", "x": 1180, "w": 480},
        {"num": "4", "name": "Chấm công & Kỷ luật Giờ giấc", "sub": "Daily Attendance & Punctuality", "x": 1680, "w": 480},
        {"num": "5", "name": "Khóa công & Nghiệm thu Cột mốc", "sub": "Monthly Lock & Acceptance", "x": 2180, "w": 480},
        {"num": "6", "name": "Hóa đơn XML & Đối soát 3 Chiều", "sub": "E-Invoice & 3-Way Auto Match", "x": 2680, "w": 480},
        {"num": "7", "name": "Lệnh MGS & Thực chi Dòng tiền", "sub": "MGS & Cash-Out Execution", "x": 3180, "w": 480},
        {"num": "8", "name": "Quyết toán, Kiểm toán & Tái ký", "sub": "Burn-Rate, Audit & Renewal", "x": 3680, "w": 460},
    ]

    swimlanes = [
        {"id": "L1", "name": "Ban Giám Đốc\n& PMO\n(Budget Owners)", "y": 180, "h": 220, "color": "#183181", "fontColor": "#ffffff"},
        {"id": "L2", "name": "Quản Lý Dự Án\n& Vận Hành (PM)\n(IT Operations)", "y": 420, "h": 240, "color": "#0284c7", "fontColor": "#ffffff"},
        {"id": "L3", "name": "Đối Tác & Nhân Sự\nGia Công (Vendors)\n(External Workforce)", "y": 680, "h": 240, "color": "#6366f1", "fontColor": "#ffffff"},
        {"id": "L4", "name": "Kế Toán &\nMua Sắm\n(Finance & Procurement)", "y": 940, "h": 240, "color": "#10b981", "fontColor": "#ffffff"},
        {"id": "L5", "name": "Nền Tảng\nMizuho VMS Core\n& Banking Gateways", "y": 1200, "h": 240, "color": "#f59e0b", "fontColor": "#000000"},
    ]

    canvas_w = 4200
    canvas_h = 1500

    xml = []
    xml.append(f"""  <diagram id="VMSBigPicture" name="1. Big Picture - End-to-End Journey">""")
    xml.append(f"""    <mxGraphModel dx="2800" dy="1600" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{canvas_w}" pageHeight="{canvas_h}" math="0" shadow="0">""")
    xml.append("""      <root>""")
    xml.append("""        <mxCell id="0" />""")
    xml.append("""        <mxCell id="1" parent="0" />""")

    # Main Header
    xml.append(f"""
    <mxCell id="main_title" value="&lt;span style=&quot;font-size: 24px; font-weight: 800;&quot;&gt;HÀNH TRÌNH TỔNG THỂ HỆ THỐNG MIZUHO VMS (END-TO-END VENDOR &amp; WORKFORCE GOVERNANCE JOURNEY)&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;font-size: 13px; font-weight: 500; color: #475569;&quot;&gt;Bức tranh lớn: Từ Lập kế hoạch Ngân sách Đầu nguồn, Quản trị Hợp đồng, Chấm công Kỷ luật, Đối soát Hóa đơn đến Giải ngân Thực chi (Cash-out) &amp; Tái ký Hợp đồng&lt;/span&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#183181;strokeWidth=2;align=left;spacingLeft=24;shadow=1;" vertex="1" parent="1">
      <mxGeometry x="10" y="10" width="{canvas_w - 40}" height="65" as="geometry" />
    </mxCell>
    <mxCell id="journey_label" value="&lt;b&gt;H&lt;br&gt;À&lt;br&gt;N&lt;br&gt;H&lt;br&gt;&lt;br&gt;T&lt;br&gt;R&lt;br&gt;Ì&lt;br&gt;N&lt;br&gt;H&lt;br&gt;&lt;br&gt;V&lt;br&gt;M&lt;br&gt;S&lt;/b&gt;" style="rounded=1;whiteSpace=wrap;html=1;fontStyle=1;fontSize=18;fillColor=#183181;strokeColor=#0f1f54;fontColor=#ffffff;align=center;shadow=1;" vertex="1" parent="1">
      <mxGeometry x="10" y="85" width="45" height="{canvas_h - 110}" as="geometry" />
    </mxCell>
    <mxCell id="actor_header_box" value="&lt;b&gt;CHỦ THỂ&lt;br&gt;&amp; VAI TRÒ&lt;/b&gt;&lt;br&gt;&lt;span style=&quot;font-size:10px; color:#64748b;&quot;&gt;(Actors / Lanes)&lt;/span&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f1f5f9;strokeColor=#cbd5e1;fontSize=12;align=center;shadow=1;" vertex="1" parent="1">
      <mxGeometry x="65" y="85" width="145" height="75" as="geometry" />
    </mxCell>
    """)

    # Stage Arrows
    colors = ["#183181", "#0284c7", "#6366f1", "#d97706", "#2563eb", "#7c3aed", "#10b981", "#ed1a3a"]
    for idx, stg in enumerate(stages):
        clr = colors[idx % len(colors)]
        arrow_shape = "notch=10;" if idx > 0 else "notch=0;"
        name_esc = html.escape(stg['name'])
        sub_esc = html.escape(stg['sub'])
        arrow_lbl = f"&lt;font color=&quot;#ffffff&quot;&gt;&lt;b&gt;({stg['num']}) {name_esc}&lt;/b&gt;&lt;br&gt;&lt;span style=&quot;font-size:10px; opacity:0.9;&quot;&gt;{sub_esc}&lt;/span&gt;&lt;/font&gt;"
        xml.append(f"""
        <mxCell id="stage_arrow_{idx}" value="{arrow_lbl}" style="html=1;shadow=1;dashed=0;align=center;verticalAlign=middle;shape=mxgraph.arrows2.arrow;dy=0;dx=12;{arrow_shape}fillColor={clr};strokeColor=#000000;strokeWidth=1;fontSize=13;fontStyle=1;" vertex="1" parent="1">
          <mxGeometry x="{stg['x']}" y="85" width="{stg['w']}" height="75" as="geometry" />
        </mxCell>
        """)

    # Swimlanes
    for lane in swimlanes:
        xml.append(f"""
        <mxCell id="lane_hdr_{lane['id']}" value="&lt;b&gt;{html.escape(lane['name'])}&lt;/b&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor={lane['color']};strokeColor=#0f172a;strokeWidth=1.5;fontStyle=1;fontSize=12;fontColor={lane['fontColor']};align=center;shadow=1;" vertex="1" parent="1">
          <mxGeometry x="65" y="{lane['y']}" width="145" height="{lane['h']}" as="geometry" />
        </mxCell>
        <mxCell id="lane_div_{lane['id']}" value="" style="endArrow=none;html=1;rounded=0;strokeColor=#cbd5e1;strokeWidth=1.5;dashed=1;" edge="1" parent="1">
          <mxGeometry width="50" height="50" relative="1" as="geometry">
            <mxPoint x="65" y="{lane['y'] + lane['h'] + 10}" as="sourcePoint" />
            <mxPoint x="{canvas_w - 30}" y="{lane['y'] + lane['h'] + 10}" as="targetPoint" />
          </mxGeometry>
        </mxCell>
        """)

    # Cards
    xml.append(create_task_card("T1_1", 240, 200, 210, 115, "Ban Giám Đốc / PMO", "Lập dự toán ngân sách IT toàn diện cho năm tài khóa (FY); phê duyệt trần ngân sách gia công (Budget Cap) theo từng khối dự án.", "Kế hoạch tài chính nội bộ Mizuho", actor_bg="#dbeafe", stroke="#183181"))
    xml.append(create_task_card("T1_2", 470, 200, 190, 115, "PMO / Trưởng Dự Án", "Phân rã ngân sách IT Outsourcing cho các dự án thành phần (Core Banking, AML, Treasury, E-Banking,...).", "Hồ sơ phê duyệt dự án nội bộ", actor_bg="#dbeafe", stroke="#183181"))
    xml.append(create_task_card("T1_3", 240, 1220, 420, 110, "Mizuho VMS Core", "Khởi tạo dự án mới trên hệ thống, nhập hạn mức 'IT Outsourcing Budget', kích hoạt theo dõi số dư thực tế và cấu hình ngưỡng cảnh báo cạn ngân sách (>75%, >90%, >100%).", "Mizuho VMS: /projects & /dashboard", actor_bg="#fef3c7", stroke="#d97706"))

    xml.append(create_task_card("T2_1", 720, 960, 200, 115, "Mua Sắm (Procurement)", "Đấu thầu, thẩm định năng lực nhà cung cấp; đàm phán khung đơn giá (Rate Card) và cam kết chất lượng dịch vụ SLA.", "Hồ sơ thầu & Vendor Portal", actor_bg="#d1fae5", stroke="#10b981"))
    xml.append(create_task_card("T2_2", 940, 700, 200, 115, "Đối Tác CNTT (Vendor Lead)", "Thống nhất điều khoản, ký kết Hợp đồng khung (Framework) và các Phụ lục (Annexes) quy định phạm vi, hạn mức giá trị và thời hạn.", "Ký kết pháp lý & Văn bản số", actor_bg="#ede9fe", stroke="#6366f1"))
    xml.append(create_task_card("T2_3", 720, 1220, 420, 115, "Mizuho VMS Core", "Lưu trữ hợp đồng & phụ lục, sinh mã thanh toán tham chiếu (Payment References), thiết lập mô hình thanh toán (T&M, Fixed Price, Recurring) và cài đặt chính sách tái ký (Auto-Renew / Manual-Renew notice 30-60d).", "Mizuho VMS: /contracts & /vendors", actor_bg="#fef3c7", stroke="#d97706"))

    xml.append(create_task_card("T3_1", 1200, 700, 210, 115, "Đối Tác CNTT (Vendor)", "Đề xuất danh sách nhân sự tham gia dự án (CV, chức danh Developer/Tester/BA, ngày bắt đầu làm việc dự kiến).", "Vendor Onboarding Form", actor_bg="#ede9fe", stroke="#6366f1"))
    xml.append(create_task_card("T3_2", 1430, 440, 215, 115, "Quản Lý Dự Án (PM)", "Phỏng vấn duyệt chuyên môn; gán nhân sự vào Phụ lục hợp đồng còn hiệu lực (Ràng buộc 100% Active Annex Coverage).", "Mizuho VMS: /staff & Annex Link", actor_bg="#e0f2fe", stroke="#0284c7"))
    xml.append(create_task_card("T3_3", 1200, 440, 215, 115, "Quản Lý Dự Án (PM)", "Phân bổ nhân sự vào dự án theo Ma trận % (Project Assignment Matrix) và thiết lập Ca làm việc chuẩn (Work Shift: 08:00-17:00 / 08:30-17:30).", "Mizuho VMS: /projects & /staff/shifts", actor_bg="#e0f2fe", stroke="#0284c7"))

    xml.append(create_task_card("T4_1", 1700, 700, 215, 115, "Nhân Sự Gia Công (Contractor)", "Chấm công hàng ngày: Check-in giờ vào, Check-out giờ ra, ghi nhận thời gian làm tiêu chuẩn và giờ làm thêm ngoài giờ (OT).", "Thẻ chấm công / Máy quét vân tay", actor_bg="#ede9fe", stroke="#6366f1"))
    xml.append(create_task_card("T4_2", 1700, 1220, 440, 115, "Mizuho VMS Core", "Tự động tính toán vi phạm giờ giấc dựa trên ca làm việc chuẩn; kết xuất 'Ma trận chấm công & kỷ luật' với ô vuông chia đường chéo 2 nửa màu (Vàng = Trễ, Đỏ = Sớm, Trắng = Chuẩn, Xám = Vắng).", "Mizuho VMS: /attendance/punctuality", actor_bg="#fef3c7", stroke="#d97706"))
    xml.append(create_task_card("T4_3", 1930, 440, 210, 115, "Quản Lý Dự Án (PM)", "Giám sát kỷ luật giờ giấc thời gian thực trên Dashboard (% On-Time Rate); yêu cầu giải trình đối với các trường hợp đi trễ hoặc về sớm bất thường.", "Mizuho VMS: Dashboard KPI & Matrix", actor_bg="#e0f2fe", stroke="#0284c7"))

    xml.append(create_task_card("T5_1", 2200, 440, 215, 115, "Quản Trị Viên (IT Admin)", "Vào ngày chốt tháng (Cut-off date), kích hoạt chức năng Khóa Bảng Công (Attendance Lock) để bảo toàn dữ liệu, chống can thiệp sau chốt.", "Mizuho VMS: /attendance Lock API", actor_bg="#e0f2fe", stroke="#0284c7"))
    xml.append(create_task_card("T5_2", 2200, 1220, 440, 115, "Mizuho VMS Core", "Tự động tính toán Bảng lương tháng (Monthly Attendance Summary): công chuẩn, công thực tế, phép năm, OT quy đổi và nhân đơn giá ngày thành chi phí T&M; quản lý cột mốc Fixed Price & Payout định kỳ.", "Mizuho VMS: /attendance/monthly & /payments", actor_bg="#fef3c7", stroke="#d97706"))
    xml.append(create_task_card("T5_3", 2430, 440, 210, 115, "PM & Vendor Lead", "Ký kết Biên bản nghiệm thu chấm công (Attendance Acceptance Certificate) hoặc nghiệm thu cột mốc chuyển giao phần mềm (Milestone Acceptance).", "Mizuho VMS: /attendance/acceptance", actor_bg="#e0f2fe", stroke="#0284c7"))

    xml.append(create_task_card("T6_1", 2700, 700, 215, 115, "Đối Tác CNTT (Vendor)", "Phát hành Hóa đơn điện tử XML (chuẩn Thông tư 78/Nghị định 123) gửi cho Ngân hàng Mizuho căn cứ trên biên bản nghiệm thu.", "Cổng hóa đơn điện tử / Email", actor_bg="#ede9fe", stroke="#6366f1"))
    xml.append(create_task_card("T6_2", 2700, 960, 215, 115, "Kế Toán Thanh Toán", "Tải file XML hóa đơn lên Mizuho VMS để hệ thống bóc tách dữ liệu số hóa đơn, ngày lập, MST bên bán, MST Mizuho và tiền thuế VAT.", "Mizuho VMS: / (Invoices Upload)", actor_bg="#d1fae5", stroke="#10b981"))
    xml.append(create_task_card("T6_3", 2930, 1220, 215, 115, "Mizuho VMS Core", "Động cơ đối soát tự động 3 chiều (Hóa đơn XML ⟷ Hợp đồng ⟷ Bảng công/Nghiệm thu) tự động phân loại: 'Matched' (100% hợp lệ), 'Mismatch', 'No Payroll', 'No Contract'.", "Mizuho VMS 3-Way Match Engine", actor_bg="#fef3c7", stroke="#d97706"))

    xml.append(create_task_card("T7_1", 3200, 1220, 215, 115, "Mizuho VMS Core", "Với hóa đơn 'Matched', hệ thống tự động sinh Biểu mẫu yêu cầu thanh toán Mizuho Global Services (MGS Form) kèm chức năng in PDF và sao chép nội dung email.", "Mizuho VMS: MGS Request Generator", actor_bg="#fef3c7", stroke="#d97706"))
    xml.append(create_task_card("T7_2", 3200, 960, 215, 115, "Kế Toán Thanh Toán", "Kiểm tra, ký duyệt biểu mẫu MGS, chuyển lệnh chi tiền qua cổng thanh toán quốc tế MGS Gateway; đánh dấu 'Sent to MGS'.", "MGS Gateway & Cổng duyệt thanh toán", actor_bg="#d1fae5", stroke="#10b981"))
    xml.append(create_task_card("T7_3", 3430, 960, 215, 115, "Kế Toán Thanh Toán", "Ghi nhận ngày tiền thực chi (Cashout Date) vào Ma trận Năm tài khóa (FY Cash-Out Matrix: 01/04 - 31/03) để tách biệt chi phí sổ sách và tiền ra thực tế.", "Mizuho VMS: /payments & /attendance/cashout", actor_bg="#d1fae5", stroke="#10b981"))
    xml.append(create_task_card("T7_4", 3430, 700, 215, 115, "Đối Tác CNTT (Vendor)", "Nhận tiền giải ngân về tài khoản doanh nghiệp; xác nhận hoàn tất thanh toán dịch vụ CNTT.", "Tài khoản Ngân hàng Doanh nghiệp", actor_bg="#ede9fe", stroke="#6366f1"))

    xml.append(create_task_card("T8_1", 3700, 200, 420, 115, "Ban Giám Đốc / PMO", "Xem Executive Dashboard thời gian thực: Phân tích cơ cấu chi tiêu 3 mô hình (T&M, Fixed Price, Recurring), tỷ lệ giải ngân so với ngân sách dự án (Burn-rate), và xu hướng chi phí.", "Mizuho VMS: /dashboard Executive KPIs", actor_bg="#dbeafe", stroke="#183181"))
    xml.append(create_task_card("T8_2", 3700, 1220, 420, 115, "Mizuho VMS Core", "Tự động rà quét các hợp đồng trong cửa sổ cảnh báo (Notice Window); kích hoạt cảnh báo 'Auto-Renew' đối với dịch vụ định kỳ hoặc nhắc nhở 'Manual-Renew' để đàm phán lại.", "Mizuho VMS Smart Renewal Engine", actor_bg="#fef3c7", stroke="#d97706"))
    xml.append(create_task_card("T8_3", 3700, 960, 420, 115, "Kiểm Toán & Tuân Thủ", "Tra soát Nhật ký kiểm toán bất biến (Immutable Audit Trail) ghi vết đầy đủ thao tác thêm/sửa/xóa/giải ngân phục vụ kiểm toán nội bộ và J-SOX.", "Mizuho VMS: /audit-logs & Export CSV", actor_bg="#d1fae5", stroke="#10b981"))

    # Edges
    edges = [
        ("E1", "T1_1", "T1_2", "Phê duyệt ngân sách"),
        ("E2", "T1_2", "T1_3", "Cấu hình trần dự án"),
        ("E3", "T1_3", "T2_1", "Yêu cầu mua sắm"),
        ("E4", "T2_1", "T2_2", "Đàm phán & ký kết"),
        ("E5", "T2_2", "T2_3", "Nhập hợp đồng & phụ lục"),
        ("E6", "T2_3", "T3_1", "Kích hoạt tiếp nhận nhân sự"),
        ("E7", "T3_1", "T3_2", "Đề xuất nhân sự"),
        ("E8", "T3_2", "T3_3", "Gán phụ lục & phân bổ ma trận"),
        ("E9", "T3_3", "T4_1", "Thiết lập ca làm việc"),
        ("E10", "T4_1", "T4_2", "Dữ liệu quẹt thẻ thực tế"),
        ("E11", "T4_2", "T4_3", "Tính toán kỷ luật ô chéo"),
        ("E12", "T4_3", "T5_1", "Đến ngày chốt tháng (Cut-off)"),
        ("E13", "T5_1", "T5_2", "Khóa công & đóng băng dữ liệu"),
        ("E14", "T5_2", "T5_3", "Tính bảng lương & nghiệm thu"),
        ("E15", "T5_3", "T6_1", "Biên bản nghiệm thu hợp lệ"),
        ("E16", "T6_1", "T6_2", "Xuất hóa đơn XML"),
        ("E17", "T6_2", "T6_3", "Tải XML đối soát 3 chiều"),
        ("E18", "T6_3", "T7_1", "Trạng thái Matched (Hợp lệ)"),
        ("E19", "T7_1", "T7_2", "Tạo biểu mẫu MGS"),
        ("E20", "T7_2", "T7_3", "Đẩy lệnh chi MGS Gateway"),
        ("E21", "T7_3", "T7_4", "Giải ngân thực chi tài khoản"),
        ("E22", "T7_3", "T8_1", "Cập nhật thực chi FY & Burn-rate"),
        ("E23", "T8_1", "T8_2", "Giám sát cảnh báo cạn ngân sách"),
        ("E24", "T8_2", "T8_3", "Cảnh báo tái ký hợp đồng & kiểm toán"),
    ]

    for edge in edges:
        xml.append(create_edge(edge[0], edge[1], edge[2], edge[3]))

    xml.append("""      </root>""")
    xml.append("""    </mxGraphModel>""")
    xml.append("""  </diagram>""")
    return "\n".join(xml)

def build_page_2():
    stages_p2 = [
        {"num": "A", "name": "Thiết lập Ca & Chấm công Hàng ngày", "sub": "Shift Setup & Daily Punch In/Out", "x": 220, "w": 480},
        {"num": "B", "name": "Phân tích Kỷ luật & Ma trận Ô chéo", "sub": "Punctuality Matrix & Discipline", "x": 720, "w": 500},
        {"num": "C", "name": "Khóa công & Tổng hợp Bảng lương T&M", "sub": "Cut-off Lock & Payroll Sign-off", "x": 1240, "w": 500},
        {"num": "D", "name": "Bóc tách XML & Đối soát Hóa đơn 3 Chiều", "sub": "Decree 123 XML & 3-Way Match", "x": 1760, "w": 520},
        {"num": "E", "name": "Lập Lệnh MGS & Giải ngân Năm tài khóa", "sub": "MGS Form & Fiscal Year Cash-out", "x": 2300, "w": 500},
    ]

    swimlanes_p2 = [
        {"id": "PL1", "name": "Nhân Sự Gia Công\n(Contractor Staff)", "y": 180, "h": 200, "color": "#6366f1", "fontColor": "#ffffff"},
        {"id": "PL2", "name": "Quản Lý Dự Án (PM)\n& IT Admin", "y": 400, "h": 220, "color": "#0284c7", "fontColor": "#ffffff"},
        {"id": "PL3", "name": "Kế Toán &\nFinance Operations", "y": 640, "h": 220, "color": "#10b981", "fontColor": "#ffffff"},
        {"id": "PL4", "name": "Động Cơ Tự Động\nMizuho VMS Core", "y": 880, "h": 240, "color": "#f59e0b", "fontColor": "#000000"},
    ]

    canvas_w = 2900
    canvas_h = 1180

    xml = []
    xml.append(f"""  <diagram id="VMSDeepDive" name="2. Deep-Dive - Punctuality &amp; 3-Way Reconciliation">""")
    xml.append(f"""    <mxGraphModel dx="2400" dy="1400" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{canvas_w}" pageHeight="{canvas_h}" math="0" shadow="0">""")
    xml.append("""      <root>""")
    xml.append("""        <mxCell id="p2_0" />""")
    xml.append("""        <mxCell id="p2_1" parent="p2_0" />""")

    # Main Header
    xml.append(f"""
    <mxCell id="p2_main_title" value="&lt;span style=&quot;font-size: 22px; font-weight: 800;&quot;&gt;QUY TRÌNH CHUYÊN SÂU: CHẤM CÔNG KỶ LUẬT Ô CHÉO &amp; ĐỐI SOÁT HÓA ĐƠN 3 CHIỀU MGS&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;font-size: 13px; font-weight: 500; color: #475569;&quot;&gt;Deep-Dive: Luồng tương tác chi tiết giữa Nhân sự, Quản lý dự án, Kế toán và Động cơ đối soát tự động của Mizuho VMS&lt;/span&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#183181;strokeWidth=2;align=left;spacingLeft=24;shadow=1;" vertex="1" parent="p2_1">
      <mxGeometry x="10" y="10" width="{canvas_w - 40}" height="65" as="geometry" />
    </mxCell>
    <mxCell id="p2_journey_label" value="&lt;b&gt;D&lt;br&gt;E&lt;br&gt;E&lt;br&gt;P&lt;br&gt;&lt;br&gt;D&lt;br&gt;I&lt;br&gt;V&lt;br&gt;E&lt;/b&gt;" style="rounded=1;whiteSpace=wrap;html=1;fontStyle=1;fontSize=18;fillColor=#0284c7;strokeColor=#0369a1;fontColor=#ffffff;align=center;shadow=1;" vertex="1" parent="p2_1">
      <mxGeometry x="10" y="85" width="45" height="{canvas_h - 110}" as="geometry" />
    </mxCell>
    <mxCell id="p2_actor_box" value="&lt;b&gt;CHỦ THỂ&lt;br&gt;&amp; VAI TRÒ&lt;/b&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f1f5f9;strokeColor=#cbd5e1;fontSize=12;align=center;shadow=1;" vertex="1" parent="p2_1">
      <mxGeometry x="65" y="85" width="145" height="75" as="geometry" />
    </mxCell>
    """)

    # Stage Arrows
    colors_p2 = ["#183181", "#0284c7", "#6366f1", "#10b981", "#ed1a3a"]
    for idx, stg in enumerate(stages_p2):
        clr = colors_p2[idx % len(colors_p2)]
        arrow_shape = "notch=10;" if idx > 0 else "notch=0;"
        name_esc = html.escape(stg['name'])
        sub_esc = html.escape(stg['sub'])
        arrow_lbl = f"&lt;font color=&quot;#ffffff&quot;&gt;&lt;b&gt;({stg['num']}) {name_esc}&lt;/b&gt;&lt;br&gt;&lt;span style=&quot;font-size:10px; opacity:0.9;&quot;&gt;{sub_esc}&lt;/span&gt;&lt;/font&gt;"
        xml.append(f"""
        <mxCell id="p2_stage_arrow_{idx}" value="{arrow_lbl}" style="html=1;shadow=1;dashed=0;align=center;verticalAlign=middle;shape=mxgraph.arrows2.arrow;dy=0;dx=12;{arrow_shape}fillColor={clr};strokeColor=#000000;strokeWidth=1;fontSize=13;fontStyle=1;" vertex="1" parent="p2_1">
          <mxGeometry x="{stg['x']}" y="85" width="{stg['w']}" height="75" as="geometry" />
        </mxCell>
        """)

    # Swimlanes
    for lane in swimlanes_p2:
        xml.append(f"""
        <mxCell id="p2_lane_hdr_{lane['id']}" value="&lt;b&gt;{html.escape(lane['name'])}&lt;/b&gt;" style="rounded=1;whiteSpace=wrap;html=1;fillColor={lane['color']};strokeColor=#0f172a;strokeWidth=1.5;fontStyle=1;fontSize=12;fontColor={lane['fontColor']};align=center;shadow=1;" vertex="1" parent="p2_1">
          <mxGeometry x="65" y="{lane['y']}" width="145" height="{lane['h']}" as="geometry" />
        </mxCell>
        <mxCell id="p2_lane_div_{lane['id']}" value="" style="endArrow=none;html=1;rounded=0;strokeColor=#cbd5e1;strokeWidth=1.5;dashed=1;" edge="1" parent="p2_1">
          <mxGeometry width="50" height="50" relative="1" as="geometry">
            <mxPoint x="65" y="{lane['y'] + lane['h'] + 10}" as="sourcePoint" />
            <mxPoint x="{canvas_w - 30}" y="{lane['y'] + lane['h'] + 10}" as="targetPoint" />
          </mxGeometry>
        </mxCell>
        """)

    # Cards for Page 2
    xml.append(create_task_card("P2_T1", 240, 420, 210, 110, "IT Admin / PM", "Cài đặt ca làm việc chuẩn (ví dụ 8:30-17:30) cho nhân sự và gán vào dự án.", "Mizuho VMS: /staff/shifts", actor_bg="#e0f2fe", stroke="#0284c7", parent_id="p2_1"))
    xml.append(create_task_card("P2_T2", 240, 200, 210, 110, "Nhân Sự Gia Công", "Thực hiện quẹt thẻ Check-in và Check-out hàng ngày; ghi nhận lý do nếu làm ngoài giờ (OT).", "Thiết bị chấm công nội bộ", actor_bg="#ede9fe", stroke="#6366f1", parent_id="p2_1"))

    xml.append(create_task_card("P2_T3", 740, 900, 460, 115, "Mizuho VMS Engine", "So sánh giờ quẹt thẻ thực tế với ca chuẩn: Check-in > giờ bắt đầu ca = Đi trễ; Check-out < giờ kết thúc ca = Về sớm. Hiển thị Ma trận Punctuality ô vuông chéo: Vàng (trên) = Trễ, Đỏ (dưới) = Sớm, Trắng = Đúng giờ, Xám = Vắng.", "Mizuho VMS: /attendance/punctuality", actor_bg="#fef3c7", stroke="#d97706", parent_id="p2_1"))
    xml.append(create_task_card("P2_T4", 740, 420, 220, 110, "Quản Lý Dự Án (PM)", "Kiểm tra tỷ lệ đúng giờ (% On-Time Rate) trên Dashboard; nhắc nhở nhân sự có vi phạm giờ giấc.", "Mizuho VMS Dashboard", actor_bg="#e0f2fe", stroke="#0284c7", parent_id="p2_1"))

    xml.append(create_task_card("P2_T5", 1260, 420, 220, 110, "IT Admin", "Thực hiện 'Khóa Bảng Chấm Công' (Lock Attendance) vào ngày cut-off; ngăn chặn mọi hành vi sửa dữ liệu.", "Mizuho VMS Lock Engine", actor_bg="#e0f2fe", stroke="#0284c7", parent_id="p2_1"))
    xml.append(create_task_card("P2_T6", 1260, 900, 460, 115, "Mizuho VMS Engine", "Tự động kết xuất Bảng lương tháng (Monthly Payroll): Tính tổng ngày công chuẩn, công thực tế, phép năm và OT quy đổi; nhân đơn giá ngày thành chi phí T&M (VND); tạo biên bản nghiệm thu chấm công.", "Mizuho VMS: /attendance/monthly", actor_bg="#fef3c7", stroke="#d97706", parent_id="p2_1"))

    xml.append(create_task_card("P2_T7", 1780, 660, 220, 110, "Kế Toán Thanh Toán", "Nhận Hóa đơn điện tử XML (chuẩn TT78) từ Vendor và tải lên hệ thống Mizuho VMS.", "Mizuho VMS: / (Invoices)", actor_bg="#d1fae5", stroke="#10b981", parent_id="p2_1"))
    xml.append(create_task_card("P2_T8", 1780, 900, 480, 115, "Mizuho VMS Engine", "Động cơ đối soát tự động 3 chiều: Bóc tách mã số thuế bên mua/bán, đối chiếu số tiền hóa đơn với bảng công chốt tháng; phân loại tức thì: Matched (khớp 100%), Mismatch, No Payroll, No Contract.", "Mizuho VMS 3-Way Engine", actor_bg="#fef3c7", stroke="#d97706", parent_id="p2_1"))

    xml.append(create_task_card("P2_T9", 2320, 900, 440, 115, "Mizuho VMS Engine", "Tự động sinh Biểu mẫu đề nghị thanh toán chuẩn Mizuho Global Services (MGS Form) với mã tham chiếu, thông tin vendor và số tiền chính xác.", "Mizuho VMS: MGS Request Form", actor_bg="#fef3c7", stroke="#d97706", parent_id="p2_1"))
    xml.append(create_task_card("P2_T10", 2320, 660, 210, 110, "Kế Toán Thanh Toán", "In bản xem trước PDF, sao chép nội dung email và duyệt gửi lệnh chi sang cổng MGS Gateway; cập nhật trạng thái 'Sent to MGS'.", "Cổng thanh toán MGS", actor_bg="#d1fae5", stroke="#10b981", parent_id="p2_1"))
    xml.append(create_task_card("P2_T11", 2550, 660, 210, 110, "Kế Toán Thanh Toán", "Ghi nhận ngày tiền thực chi (Cashout Date) vào Ma trận Năm tài khóa để hoàn tất vòng đời giải ngân.", "Mizuho VMS: /payments Cashout", actor_bg="#d1fae5", stroke="#10b981", parent_id="p2_1"))

    # Edges for Page 2
    edges_p2 = [
        ("P2_E1", "P2_T1", "P2_T2", "Ca làm việc áp dụng"),
        ("P2_E2", "P2_T2", "P2_T3", "Dữ liệu quẹt thẻ thực tế"),
        ("P2_E3", "P2_T3", "P2_T4", "Kết xuất Ma trận ô chéo"),
        ("P2_E4", "P2_T4", "P2_T5", "Đến ngày chốt tháng (Cut-off)"),
        ("P2_E5", "P2_T5", "P2_T6", "Đóng băng dữ liệu & tính lương"),
        ("P2_E6", "P2_T6", "P2_T7", "Biên bản nghiệm thu chuyển Kế toán"),
        ("P2_E7", "P2_T7", "P2_T8", "Tải XML đối soát 3 chiều"),
        ("P2_E8", "P2_T8", "P2_T9", "Hóa đơn Matched hợp lệ"),
        ("P2_E9", "P2_T9", "P2_T10", "Tạo biểu mẫu thanh toán MGS"),
        ("P2_E10", "P2_T10", "P2_T11", "Đẩy lệnh MGS & Cập nhật Cashout Date"),
    ]

    for edge in edges_p2:
        xml.append(create_edge(edge[0], edge[1], edge[2], edge[3], parent_id="p2_1"))

    xml.append("""      </root>""")
    xml.append("""    </mxGraphModel>""")
    xml.append("""  </diagram>""")
    return "\n".join(xml)

def build_full_file():
    parts = []
    parts.append("""<mxfile host="Electron" modified="2026-11-18T03:30:00.000Z" agent="Mozilla/5.0" version="24.6.4" type="device" pages="2">""")
    parts.append(build_page_1())
    parts.append(build_page_2())
    parts.append("""</mxfile>""")
    return "\n".join(parts)

if __name__ == "__main__":
    out_file = "/Users/local/04.working/17.mizuho/vendor_management/cj/mizuho_vms_customer_journey.drawio"
    drawio_data = build_full_file()
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(drawio_data)
    print(f"Customer Journey Draw.io file successfully generated: {out_file}")
