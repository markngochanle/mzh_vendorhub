# audit.py
from html import escape
import urllib.parse
from common import db_connect, layout, send_html

def page_audit_logs(handler):
    # Parse query parameters
    parsed_path = urllib.parse.urlparse(handler.path)
    query_params = urllib.parse.parse_qs(parsed_path.query)
    
    page_raw = query_params.get("page", ["1"])[0]
    action_filter = query_params.get("action", [""])[0].strip()
    search_query = query_params.get("search", [""])[0].strip()
    
    page = int(page_raw) if page_raw.isdigit() else 1
    if page < 1:
        page = 1
        
    limit = 50
    offset = (page - 1) * limit
    
    conn = db_connect()
    try:
        # Build query filters
        where_clauses = []
        params = []
        
        if action_filter:
            where_clauses.append("action = ?")
            params.append(action_filter)
        if search_query:
            where_clauses.append("(description LIKE ? OR table_name LIKE ?)")
            params.append(f"%{search_query}%")
            params.append(f"%{search_query}%")
            
        where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Get count
        total_count = conn.execute(f"SELECT COUNT(*) FROM audit_logs {where_str}", params).fetchone()[0]
        
        # Fetch logs
        logs_query = f"""
            SELECT * FROM audit_logs 
            {where_str} 
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        """
        logs = conn.execute(logs_query, params + [limit, offset]).fetchall()
        
        # Fetch unique actions for filter dropdown
        unique_actions = [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action ASC").fetchall()]
        
    finally:
        conn.close()
        
    # Render Action Options
    action_opts = ['<option value="">-- all actions --</option>']
    for a in unique_actions:
        sel = "selected" if a == action_filter else ""
        action_opts.append(f'<option value="{escape(a)}" {sel}>{escape(a)}</option>')
        
    # Render table rows
    rows_html = []
    for log in logs:
        # Tag style by action type
        act = log["action"]
        if "CREATE" in act or "ADD" in act or "IMPORT" in act or "UPLOAD" in act:
            act_style = "background:#e6f4ea; border-color:#b4e3be; color:#137333;"
        elif "DELETE" in act or "REMOVE" in act or "DEACTIVATE" in act:
            act_style = "background:#fce8e6; border-color:#fad2cf; color:#c5221f;"
        elif "UPDATE" in act or "EDIT" in act or "TOGGLE" in act or "FORCE" in act:
            act_style = "background:#fef7e0; border-color:#feebc8; color:#b06000;"
        else:
            act_style = "background:#f1f5f9; border-color:#cbd5e1; color:#475569;"
            
        tbl_info = f'<span class="tag" style="margin:0; background:#f8fafc; font-size:11px;">{escape(log["table_name"] or "")} #{log["record_id"]}</span>' if log["table_name"] else ""
        
        rows_html.append(f"""
        <tr>
          <td style="white-space:nowrap; font-size:13px; color:var(--text-secondary);">{escape(log["created_at"])}</td>
          <td><span class="tag" style="{act_style} font-size:11px; font-weight:600; text-transform:uppercase; margin-left:0;">{escape(act)}</span></td>
          <td>{tbl_info}</td>
          <td><strong>{escape(log["description"])}</strong></td>
        </tr>
        """)
        
    # Pagination controls
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
    
    prev_url = f"/audit-logs?page={page-1}&action={urllib.parse.quote(action_filter)}&search={urllib.parse.quote(search_query)}" if page > 1 else "#"
    next_url = f"/audit-logs?page={page+1}&action={urllib.parse.quote(action_filter)}&search={urllib.parse.quote(search_query)}" if page < total_pages else "#"
    
    prev_disabled = "disabled style='opacity:0.5; cursor:not-allowed;'" if page <= 1 else ""
    next_disabled = "disabled style='opacity:0.5; cursor:not-allowed;'" if page >= total_pages else ""
    
    body = f"""
    <div style="margin-bottom: 24px;">
      <h2 style="margin: 0 0 6px 0; color: var(--text-primary);">Audit Logs</h2>
      <p style="margin: 0; color: var(--text-muted); font-size: 14px;">Nhật ký ghi nhận lịch sử các hành động thay đổi dữ liệu trên hệ thống.</p>
    </div>

    <div class="card" style="margin-bottom: 20px; padding: 16px;">
      <form method="GET" action="/audit-logs" class="filters" style="display:flex; gap:16px; flex-wrap:wrap; align-items:flex-end;">
        <div style="flex:1; min-width:200px;">
          <div class="label">Tìm kiếm nội dung</div>
          <input type="text" name="search" placeholder="Nhập từ khóa cần tìm..." value="{escape(search_query)}" style="width:100%;">
        </div>
        <div style="width:200px;">
          <div class="label">Hành động (Action)</div>
          <select name="action" style="width:100%;">
            {''.join(action_opts)}
          </select>
        </div>
        <div>
          <button type="submit" class="btn-primary">Tìm kiếm</button>
          <a href="/audit-logs" class="btn btn-secondary">Reset</a>
        </div>
      </form>
    </div>

    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse; margin:0; border:none;">
        <thead>
          <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
            <th style="width:160px; text-align:left; padding:12px 16px;">Thời gian</th>
            <th style="width:140px; text-align:left; padding:12px 16px;">Hành động</th>
            <th style="width:160px; text-align:left; padding:12px 16px;">Bảng & ID</th>
            <th style="text-align:left; padding:12px 16px;">Chi tiết hoạt động</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html) if rows_html else '<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--text-muted);">Không tìm thấy nhật ký hoạt động nào.</td></tr>'}
        </tbody>
      </table>
    </div>

    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px; font-size:13.5px;">
      <div class="muted">Hiển thị từ {(page-1)*limit + 1 if total_count > 0 else 0} đến {min(page*limit, total_count)} trong tổng số <b>{total_count}</b> dòng</div>
      <div style="display:flex; gap:8px;">
        <a href="{prev_url}" class="btn" {prev_disabled}>← Trang trước</a>
        <span style="display:inline-flex; align-items:center; padding:0 8px; font-weight:600;">Trang {page} / {total_pages}</span>
        <a href="{next_url}" class="btn" {next_disabled}>Trang sau →</a>
      </div>
    </div>
    """
    
    send_html(handler, layout("Audit Logs", body))
