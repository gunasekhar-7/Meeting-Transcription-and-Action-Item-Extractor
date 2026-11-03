"""Meeting Intelligence dashboard.

Run with: streamlit run frontend/streamlit_app/app.py
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import streamlit as st

try:  # streamlit run executes this file as a script, not a package module
    from .api_client import ApiClient, ApiError
except ImportError:  # pragma: no cover - script execution path
    from api_client import ApiClient, ApiError

st.set_page_config(page_title="Meeting Intelligence", page_icon="🎙️", layout="wide")

STATUS_COLOURS = {
    "ready": "🟢",
    "processing": "🟡",
    "created": "⚪",
    "failed": "🔴",
}


def get_client() -> ApiClient:
    if "client" not in st.session_state:
        st.session_state.client = ApiClient()
    return st.session_state.client


def fmt_ms(value: int | None) -> str:
    if value is None:
        return "—"
    seconds = value // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def evidence_block(evidence: list[dict[str, Any]]) -> None:
    for link in evidence:
        st.caption(
            f'“{link["quote"]}”  ·  segment {link["segment_id"]}  ·  '
            f'{fmt_ms(link["start_ms"])}'
        )


def login_screen(client: ApiClient) -> None:
    st.title("Meeting Intelligence")
    st.write(
        "Upload a recording and get a timestamped transcript, decisions, and action "
        "items — each one backed by the exact words that justified it."
    )
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])

    with login_tab:
        with st.form("login"):
            email = st.text_input("Email", value="")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            try:
                client.login(email, password)
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

    with register_tab:
        with st.form("register"):
            new_email = st.text_input("Email", key="register_email")
            display_name = st.text_input("Display name")
            new_password = st.text_input("Password (12+ characters)", type="password")
            create = st.form_submit_button("Create account", use_container_width=True)
        if create:
            try:
                client.register(new_email, new_password, display_name)
                client.login(new_email, new_password)
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))


def sidebar(client: ApiClient) -> str:
    with st.sidebar:
        st.title("🎙️ Meeting Intelligence")
        try:
            user = client.me()
            st.caption(f"Signed in as **{user['display_name']}**")
        except ApiError:
            client.clear()
            st.rerun()
        page = st.radio(
            "Navigate",
            ["Dashboard", "Upload", "Meetings", "Action items"],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("Sign out", use_container_width=True):
            client.logout()
            st.rerun()
    return page


def dashboard_page(client: ApiClient) -> None:
    st.header("Dashboard")
    summary = client.dashboard()
    meetings = summary["meetings"]
    items = summary["action_items"]

    columns = st.columns(4)
    columns[0].metric("Meetings", meetings.get("total", 0))
    columns[1].metric("Ready", meetings.get("ready", 0))
    columns[2].metric("Open action items", items.get("open", 0) + items.get("in_progress", 0))
    columns[3].metric("Overdue", items.get("overdue", 0))

    left, right = st.columns(2)
    with left:
        st.subheader("Recent meetings")
        if not summary["recent_meetings"]:
            st.info("No meetings yet. Upload a recording to get started.")
        for meeting in summary["recent_meetings"]:
            st.write(
                f"{STATUS_COLOURS.get(meeting['status'], '⚪')} **{meeting['title']}** · "
                f"{meeting['created_at'][:10]}"
            )
    with right:
        st.subheader("Upcoming deadlines")
        if not summary["upcoming_due"]:
            st.info("No dated action items.")
        for item in summary["upcoming_due"]:
            st.write(f"**{item['due_date']}** · {item['title']} · _{item['meeting_title']}_")


def upload_page(client: ApiClient) -> None:
    st.header("Upload a meeting")
    st.caption(
        "Supported: WAV, MP3, M4A, FLAC, OGG, WebM. "
        "The recording is processed in the background; this page polls for progress."
    )

    with st.form("upload"):
        title = st.text_input("Meeting title", max_chars=200)
        description = st.text_area("Description (optional)", max_chars=5000)
        set_date = st.checkbox("Set the meeting date")
        meeting_date = st.date_input("Meeting date", value=date.today()) if set_date else None
        uploaded = st.file_uploader(
            "Audio file", type=["wav", "mp3", "m4a", "flac", "ogg", "webm"]
        )
        submit = st.form_submit_button("Upload and process", type="primary")

    if not submit:
        return
    if not title.strip() or uploaded is None:
        st.error("A title and an audio file are required.")
        return

    try:
        meeting = client.create_meeting(
            title=title.strip(),
            description=description.strip() or None,
            meeting_date=meeting_date.isoformat() if meeting_date else None,
        )
        client.upload(
            meeting["id"],
            uploaded.name,
            uploaded.getvalue(),
            uploaded.type or "application/octet-stream",
        )
    except ApiError as exc:
        st.error(str(exc))
        return

    st.success("Upload accepted. Processing started.")
    progress = st.progress(5)
    stage_box = st.empty()
    result = None
    for _ in range(300):
        try:
            result = client.status(meeting["id"])
        except ApiError as exc:
            st.error(str(exc))
            return
        stages = {stage["name"]: stage for stage in result["stages"]}
        current = max(stages.values(), key=lambda stage: stage["progress"])
        progress.progress(min(95, max(5, current["progress"])))
        stage_box.info(
            f"Stage: **{current['name']}** · {current['status']} · "
            f"{current['progress']}%"
        )
        if result["status"] in {"ready", "failed"}:
            break
        time.sleep(2)

    progress.progress(100)
    if result is None:
        st.error("Processing did not report a status.")
    elif result["status"] == "failed":
        error = result.get("error") or {}
        st.error(error.get("message", "Processing failed."))
        if error.get("retryable"):
            st.caption("This failure is retryable; open the meeting and run analysis again.")
    else:
        st.session_state["meeting_id"] = meeting["id"]
        st.success("Meeting processed. Open the Meetings page to review it.")


def render_action_editor(
    client: ApiClient,
    item: dict[str, Any],
    speakers: dict[str, str | None],
    meeting_id: str,
) -> None:
    speaker_names = {label: speaker_id for label, speaker_id in speakers.items()}
    current_label = next(
        (label for label, speaker_id in speaker_names.items() if speaker_id == item["owner_speaker_id"]),
        "Unassigned",
    )
    with st.form(f"action-{item['id']}"):
        title = st.text_input("Title", value=item["title"], key=f"title-{item['id']}")
        owner = st.selectbox(
            "Owner",
            list(speaker_names.keys()),
            index=list(speaker_names.keys()).index(current_label),
            key=f"owner-{item['id']}",
        )
        status = st.selectbox(
            "Status",
            ["open", "in_progress", "blocked", "done", "cancelled"],
            index=["open", "in_progress", "blocked", "done", "cancelled"].index(item["status"]),
            key=f"status-{item['id']}",
        )
        priority = st.selectbox(
            "Priority",
            ["unknown", "low", "medium", "high", "critical"],
            index=["unknown", "low", "medium", "high", "critical"].index(item["priority"]),
            key=f"priority-{item['id']}",
        )
        has_due = st.checkbox(
            "Has a due date", value=item["due_date"] is not None, key=f"due-{item['id']}"
        )
        due = st.date_input(
            "Due date",
            value=date.fromisoformat(item["due_date"]) if item["due_date"] else date.today(),
            key=f"duedate-{item['id']}",
        )
        if st.form_submit_button("Save changes"):
            payload: dict[str, Any] = {
                "title": title,
                "owner_speaker_id": speaker_names[owner],
                "status": status,
                "priority": priority,
                "due_date": due.isoformat() if has_due else None,
            }
            try:
                client.update_action_item(item["id"], payload)
                st.success("Saved.")
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

    if item.get("evidence"):
        st.caption("Evidence")
        evidence_block(item["evidence"])
    if item.get("due_date_text") and not item.get("due_date"):
        st.caption(f"Original phrasing: “{item['due_date_text']}” (no calendar date resolved)")


def meetings_page(client: ApiClient) -> None:
    st.header("Meetings")
    search = st.text_input("Search meetings", placeholder="Title or description")
    try:
        meetings = client.list_meetings(q=search or None)["items"]
    except ApiError as exc:
        st.error(str(exc))
        return

    if not meetings:
        st.info("No meetings match.")
        return

    labels = {
        f"{STATUS_COLOURS.get(meeting['status'], '⚪')} {meeting['title']} · {meeting['created_at'][:10]}": meeting
        for meeting in meetings
    }
    default_id = st.session_state.get("meeting_id")
    default_index = 0
    if default_id:
        for index, meeting in enumerate(labels.values()):
            if meeting["id"] == default_id:
                default_index = index
                break
    selected_label = st.selectbox("Select a meeting", list(labels.keys()), index=default_index)
    meeting = labels[selected_label]

    st.subheader(meeting["title"])
    st.caption(
        f"Status: {meeting['status']} · Intelligence: {meeting['intelligence_status']} · "
        f"{meeting['action_item_count']} action items · {meeting['speaker_count']} speakers"
    )

    if meeting["status"] not in {"ready", "failed"}:
        st.info("This meeting is still processing. Refresh in a moment.")
        return
    if meeting["intelligence_status"] == "failed":
        st.warning("Transcription succeeded, but analysis failed.")
        if st.button("Re-run analysis"):
            try:
                client.analyze(meeting["id"])
                st.success("Analysis re-queued.")
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

    try:
        transcript = client.transcript(meeting["id"])
    except ApiError:
        st.warning("Transcript is not ready.")
        transcript = None

    intelligence = None
    if meeting["intelligence_status"] == "ready":
        try:
            intelligence = client.intelligence(meeting["id"])
        except ApiError as exc:
            st.warning(str(exc))

    tabs = st.tabs(["Transcript", "Summary", "Decisions", "Action items", "Export"])

    with tabs[0]:
        if transcript is None:
            st.info("No transcript yet.")
        else:
            speaker_names = {
                speaker["label"]: speaker["display_name"] or speaker["label"]
                for speaker in transcript["speakers"]
            }
            st.caption(
                f"Language: {transcript['language'] or 'unknown'} · "
                f"{transcript['total']} segments · ASR: {transcript['asr']['provider']} "
                f"({transcript['asr']['model']})"
            )
            if transcript.get("capability_notes"):
                st.caption(f"Capabilities: {transcript['capability_notes']}")
            query = st.text_input("Search this transcript", key="transcript_search")
            if query and len(query) >= 2:
                hits = client.search_transcript(meeting["id"], query)
                st.write(f"{hits['total']} matches")
                for hit in hits["hits"]:
                    st.markdown(f"**{fmt_ms(hit['start_ms'])}** · {hit['speaker_label'] or '—'}")
                    st.write(hit["snippet"])
                st.divider()
            for segment in transcript["segments"]:
                speaker = speaker_names.get(segment["speaker_label"], "Unknown")
                st.markdown(f"**{speaker}** · `{fmt_ms(segment['start_ms'])}`")
                st.write(segment["text"])

    with tabs[1]:
        if intelligence is None:
            st.info("No analysis available.")
        else:
            st.subheader("Summary")
            st.write(intelligence["summary_short"])
            st.write(intelligence["summary_detailed"])
            if intelligence["topics"]:
                st.caption("Topics: " + ", ".join(intelligence["topics"]))
            st.subheader("Key points")
            for point in intelligence["key_points"]:
                st.markdown(f"- {point['text']}")
                evidence_block(point["evidence"])
            st.caption(
                f"Model: {intelligence['llm']['model']} · prompt {intelligence['llm']['prompt_version']}"
            )

    with tabs[2]:
        if intelligence is None or not intelligence["decisions"]:
            st.info("No grounded decisions were extracted.")
        else:
            for decision in intelligence["decisions"]:
                st.markdown(f"**{decision['text']}**")
                if decision["rationale"]:
                    st.write(decision["rationale"])
                evidence_block(decision["evidence"])

    with tabs[3]:
        if transcript is None:
            st.info("No transcript yet.")
        else:
            speakers = {"Unassigned": None}
            speakers.update(
                {
                    speaker["display_name"] or speaker["label"]: speaker["id"]
                    for speaker in transcript["speakers"]
                }
            )
            if intelligence is None or not intelligence["action_items"]:
                st.info("No grounded action items were extracted.")
            for item in intelligence["action_items"] if intelligence else []:
                with st.expander(f"{item['title']} · {item['status']}"):
                    render_action_editor(client, item, speakers, meeting["id"])

    with tabs[4]:
        fmt = st.selectbox("Format", ["json", "md", "txt", "srt", "vtt"])
        if st.button("Prepare download"):
            try:
                content, content_type = client.download(meeting["id"], fmt)
                st.session_state["export"] = (content, content_type, fmt)
            except ApiError as exc:
                st.error(str(exc))
        if "export" in st.session_state:
            content, content_type, exported_fmt = st.session_state["export"]
            st.download_button(
                f"Download .{exported_fmt}",
                data=content,
                file_name=f"meeting.{exported_fmt}",
                mime=content_type,
            )


def action_items_page(client: ApiClient) -> None:
    st.header("Action items")
    left, right = st.columns(2)
    with left:
        statuses = st.multiselect(
            "Status",
            ["open", "in_progress", "blocked", "done", "cancelled"],
            default=["open", "in_progress", "blocked"],
        )
    with right:
        overdue = st.checkbox("Overdue only")

    params: dict[str, Any] = {}
    if statuses:
        params["status"] = statuses
    if overdue:
        params["overdue"] = "true"

    try:
        page = client.list_action_items(params)
    except ApiError as exc:
        st.error(str(exc))
        return

    st.caption(f"{page['total']} action items")
    if not page["items"]:
        st.info("Nothing matches these filters.")

    for item in page["items"]:
        flag = " · **overdue**" if item["due_date"] and item["due_date"] < date.today().isoformat() and item["status"] not in {"done", "cancelled"} else ""
        with st.expander(f"{item['title']} — {item['status']}{flag}"):
            st.caption(
                f"{item['meeting_title']} · owner: {item['owner_display_name'] or 'unassigned'} "
                f"· due: {item['due_date'] or 'not resolved'} · priority: {item['priority']}"
            )
            if st.button("Mark done", key=f"done-{item['id']}"):
                try:
                    client.update_action_item(item["id"], {"status": "done"})
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))


def main() -> None:
    client = get_client()
    if not client.access_token:
        login_screen(client)
        return

    page = sidebar(client)
    try:
        if page == "Dashboard":
            dashboard_page(client)
        elif page == "Upload":
            upload_page(client)
        elif page == "Meetings":
            meetings_page(client)
        else:
            action_items_page(client)
    except ApiError as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
