# roles/mentor.py

import streamlit as st
from database import supabase
from datetime import datetime, timedelta
from utils.helpers import format_datetime_safe
from utils.session_creator import create_session_with_meet_and_email
from emailer import send_email
import uuid
import pytz

WAT = pytz.timezone("Africa/Lagos")

def parse_datetime_safe(dt):
    if isinstance(dt, datetime):
        return dt.astimezone(WAT)
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt).astimezone(WAT)
        except ValueError:
            return None
    return None

def classify_session(start_time_str, end_time_str):
    now = datetime.now(WAT)
    start = parse_datetime_safe(start_time_str)
    end = parse_datetime_safe(end_time_str)

    if not start or not end:
        return "Invalid", "❌"
    if end < now:
        return "Past", "🟥"
    elif start <= now <= end:
        return "Ongoing", "🟨"
    else:
        return "Upcoming", "🟩"

def show():
    st.title("Mentor Dashboard")
    st.info("Manage your sessions, availability, profile, and mentorship requests.")
    mentor_id = st.session_state.user["userid"]

    tabs = st.tabs([
        "🏠 Dashboard",
        "📌 Availability",
        "📥 Requests",
        "📅 Sessions"
    ])

    # --- Dashboard Tab ---
    with tabs[0]:
        st.subheader("Welcome to your Mentor Dashboard")

        profile_data = supabase.table("profile").select("*").eq("userid", mentor_id).execute().data
        profile = profile_data[0] if profile_data else {}

        total_requests = supabase.table("mentorshiprequest").select("mentorshiprequestid").eq("mentorid", mentor_id).execute().data or []
        total_sessions = supabase.table("session").select("sessionid").eq("mentorid", mentor_id).execute().data or []

        st.markdown("### 📊 Summary")
        st.write(f"- 📥 Incoming Requests: **{len(total_requests)}**")
        st.write(f"- 📅 Total Sessions: **{len(total_sessions)}**")

        st.markdown("### 🙍‍♂️ Update Profile")

        if profile.get("profile_image_url"):
            st.image(profile["profile_image_url"], width=100, caption="Current Profile Picture")

        with st.form("mentor_profile_form"):
            name = st.text_input("Name", value=profile.get("name", ""))
            bio = st.text_area("Bio", value=profile.get("bio", ""))
            skills = st.text_area("Skills", value=profile.get("skills", ""))
            goals = st.text_area("Goals", value=profile.get("goals", ""))
            profile_image = st.file_uploader("Upload Profile Picture", type=["jpg", "jpeg", "png"])

            if st.form_submit_button("Update Profile"):
                update_data = {
                    "userid": mentor_id,
                    "name": name,
                    "bio": bio,
                    "skills": skills,
                    "goals": goals,
                }

                if profile_image:
                    try:
                        file_ext = profile_image.type.split("/")[-1]
                        file_name = f"{mentor_id}_{uuid.uuid4()}.{file_ext}"
                        file_bytes = profile_image.getvalue()
                        supabase.storage.from_("profilepics").upload(file_name, file_bytes)
                        public_url = supabase.storage.from_("profilepics").get_public_url(file_name)
                        update_data["profile_image_url"] = public_url
                    except Exception as e:
                        st.error(f"Profile image upload failed: {e}")

                supabase.table("profile").upsert(update_data, on_conflict=["userid"]).execute()
                st.success("✅ Profile updated successfully!")
                st.rerun()

    # --- Availability Tab ---
    with tabs[1]:
        st.subheader("Add Availability Slot")

        with st.form(f"availability_form_{mentor_id}", clear_on_submit=True):
            now_wat = datetime.now(WAT)
            date = st.date_input("Date", value=now_wat.date())
            start_time = st.time_input("Start Time", value=(now_wat + timedelta(hours=1)).time())
            end_time = st.time_input("End Time", value=(now_wat + timedelta(hours=2)).time())
            submitted = st.form_submit_button("➕ Add Slot")

            if submitted:
                start = WAT.localize(datetime.combine(date, start_time))
                end = WAT.localize(datetime.combine(date, end_time))

                if end <= start:
                    st.warning("End time must be after start time.")
                else:
                    try:
                        supabase.table("availability").insert({
                            "mentorid": mentor_id,
                            "start": start.isoformat(),
                            "end": end.isoformat()
                        }).execute()
                        st.success(f"Availability added: {format_datetime_safe(start)} ➡ {format_datetime_safe(end)}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to add availability: {e}")

        st.markdown("### Existing Availability")
        slots = supabase.table("availability").select("*").eq("mentorid", mentor_id).execute().data or []

        if slots:
            for slot in slots:
                start = format_datetime_safe(slot["start"], tz=WAT)
                end = format_datetime_safe(slot["end"], tz=WAT)
                col1, col2 = st.columns([6, 1])
                col1.markdown(f"- 🕒 {start} ➡ {end}")
                if col2.button("❌", key=f"delete_slot_{slot['availabilityid']}"):
                    try:
                        supabase.table("availability").delete().eq("availabilityid", slot["availabilityid"]).execute()
                        st.success("Availability removed.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to remove slot: {e}")
        else:
            st.info("No availability slots added yet.")

    # --- Requests Tab ---
    with tabs[2]:
        st.subheader("Incoming Mentorship Requests")
        requests = supabase.table("mentorshiprequest") \
            .select("*, mentee:users!mentorshiprequest_menteeid_fkey(email, userid)") \
            .eq("mentorid", mentor_id).eq("status", "PENDING").execute().data or []

        if not requests:
            st.info("No pending requests.")
        else:
            for req in requests:
                mentee = req.get("mentee", {})
                mentee_email = mentee.get("email", "Unknown")
                mentee_id = mentee.get("userid")
                req_id = req["mentorshiprequestid"]

                mentee_profile_data = supabase.table("profile").select("*").eq("userid", mentee_id).execute().data
                mentee_profile = mentee_profile_data[0] if mentee_profile_data else {}

                with st.expander(f"Request from {mentee_email}"):
                    if mentee_profile.get("profile_image_url"):
                        st.image(mentee_profile["profile_image_url"], width=100)

                    st.markdown(f"""
                    **Name:** {mentee_profile.get("name", "N/A")}  
                    **Bio:** {mentee_profile.get("bio", "N/A")}  
                    **Skills:** {mentee_profile.get("skills", "N/A")}  
                    **Goals:** {mentee_profile.get("goals", "N/A")}
                    """)

                    col1, col2 = st.columns(2)
                    if col1.button("✅ Accept", key=f"accept_{req_id}"):
                        now = datetime.now(WAT)
                        start = now + timedelta(minutes=5)
                        end = start + timedelta(minutes=30)

                        success, msg = create_session_with_meet_and_email(
                            supabase, mentor_id, mentee_id, start, end
                        )

                        if success:
                            supabase.table("mentorshiprequest").update({"status": "ACCEPTED"}) \
                                .eq("mentorshiprequestid", req_id).execute()
                            st.success("Request accepted and session booked!")
                            st.rerun()
                        else:
                            st.error(msg)

                    if col2.button("❌ Reject", key=f"reject_{req_id}"):
                        supabase.table("mentorshiprequest").update({"status": "REJECTED"}) \
                            .eq("mentorshiprequestid", req_id).execute()
                        st.info("Request rejected.")
                        st.rerun()

    # --- Sessions Tab ---
    with tabs[3]:
        st.subheader("Your Mentorship Sessions")
        sessions = supabase.table("session").select("*, users!session_menteeid_fkey(email)") \
            .eq("mentorid", mentor_id).execute().data or []

        if sessions:
            for s in sessions:
                mentee_email = s.get("users", {}).get("email", "Unknown")
                start_str = s.get("start")
                end_str = s.get("end")
                meet_link = s.get("meet_link", "#")

                status, emoji = classify_session(start_str, end_str)
                start_fmt = format_datetime_safe(start_str, tz=WAT)
                end_fmt = format_datetime_safe(end_str, tz=WAT)

                st.markdown(f"""
                ### {emoji} {status} Session
                - 👤 With: **{mentee_email}**
                - 🕒 Start: {start_fmt}
                - 🕔 End: {end_fmt}
                - 🔗 [Join Meet]({meet_link})
                """)

                if st.button("📧 Send Reminder", key=f"reminder_{s['sessionid']}"):
                    if send_email(
                        to_email=mentee_email,
                        subject="📅 Mentorship Session Reminder",
                        body=f"This is a reminder for your session scheduled on {start_fmt}.\n\nJoin via Meet: {meet_link}"
                    ):
                        st.success("Reminder email sent!")
                    else:
                        st.error("Failed to send reminder.")
        else:
            st.info("No sessions yet.")
