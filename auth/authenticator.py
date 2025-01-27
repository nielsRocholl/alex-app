import streamlit as st
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from auth.token_manager import AuthTokenManager


class Authenticator:
    def __init__(
        self,
        cookie_name: str = "auth_jwt",
        token_duration_days: int = 1,
    ):
        st.session_state["connected"] = st.session_state.get("connected", False)
        self.allowed_users = st.secrets["app"]["allowed_users"]
        self.token_key = st.secrets["app"]["token_key"]
        self.client_config = {
            "web": {
                "client_id": st.secrets["google"]["client_id"],
                "project_id": st.secrets["google"]["project_id"],
                "auth_uri": st.secrets["google"]["auth_uri"],
                "token_uri": st.secrets["google"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["google"]["auth_provider_x509_cert_url"],
                "client_secret": st.secrets["google"]["client_secret"],
                "redirect_uris": st.secrets["google"]["redirect_uris"]
            }
        }
        self.auth_token_manager = AuthTokenManager(
            cookie_name=cookie_name,
            token_key=self.token_key,
            token_duration_days=token_duration_days,
        )
        self.cookie_name = cookie_name

    def _initialize_flow(self) -> google_auth_oauthlib.flow.Flow:
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            self.client_config,
            scopes=[
                "openid",
                "https://www.googleapis.com/auth/userinfo.profile",
                "https://www.googleapis.com/auth/userinfo.email",
            ],
            redirect_uri=self.client_config["web"]["redirect_uris"][0]
        )
        return flow

    def get_auth_url(self) -> str:
        flow = self._initialize_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true"
        )
        return auth_url

    def login(self):
        if not st.session_state["connected"]:
            auth_url = self.get_auth_url()
            st.link_button("login with google", auth_url,  use_container_width=True)


    def check_auth(self):
        # If already connected, don't show the toast repeatedly
        if st.session_state.get("connected"):
            return

        if st.session_state.get("logout"):
            st.toast(":green[user logged out]")
            return

        token = self.auth_token_manager.get_decoded_token()
        if token is not None:
            st.session_state["connected"] = True
            st.session_state["user_info"] = {
                "email": token["email"],
                "oauth_id": token["oauth_id"],
            }
            st.rerun()  # Update session state

        auth_code = st.query_params.get("code")
        if auth_code:
            st.query_params.clear()
            flow = self._initialize_flow()
            flow.fetch_token(code=auth_code)
            creds = flow.credentials

            oauth_service = build(serviceName="oauth2", version="v2", credentials=creds)
            user_info = oauth_service.userinfo().get().execute()
            oauth_id = user_info.get("id")
            email = user_info.get("email")

            if email in self.allowed_users:
                self.auth_token_manager.set_token(email, oauth_id)
                st.session_state["connected"] = True
                st.session_state["user_info"] = {
                    "oauth_id": oauth_id,
                    "email": email,
                }
                st.toast(":green[user is authenticated]")  # Only show during actual login
            else:
                st.toast(":red[access denied: Unauthorized user]")

    def logout(self):
        st.session_state["logout"] = True
        st.session_state["user_info"] = None
        st.session_state["connected"] = None
        self.auth_token_manager.delete_token()
        # no rerun
