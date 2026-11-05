from __future__ import annotations

import httpx

from ...application.ports.github_oauth import (
    GitHubIdentity,
    GitHubOAuthError,
    GitHubOAuthProvider,
)


class HttpGitHubOAuthProvider(GitHubOAuthProvider):
    """Authenticate GitHub OAuth codes using GitHub's HTTPS API."""

    async def authenticate(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> GitHubIdentity:
        """Exchange a code and select a verified primary email."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                token_response = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    json={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
                token_response.raise_for_status()
                access_token = token_response.json().get("access_token")
                if not isinstance(access_token, str):
                    raise GitHubOAuthError("authorization_rejected")

                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                user_response = await client.get(
                    "https://api.github.com/user",
                    headers=headers,
                )
                user_response.raise_for_status()
                user = user_response.json()
                emails_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers=headers,
                )
                emails_response.raise_for_status()
                emails = emails_response.json()
        except GitHubOAuthError:
            raise
        except httpx.HTTPError as exc:
            raise GitHubOAuthError("provider_unavailable") from exc

        if not isinstance(user, dict) or not isinstance(emails, list):
            raise GitHubOAuthError("invalid_provider_response")
        github_id = str(user.get("id", ""))
        verified = [
            item
            for item in emails
            if isinstance(item, dict)
            and item.get("verified") is True
            and isinstance(item.get("email"), str)
        ]
        primary = next(
            (item for item in verified if item.get("primary") is True),
            verified[0] if verified else None,
        )
        if not github_id or primary is None:
            raise GitHubOAuthError("verified_email_required")
        email = primary["email"]
        if not isinstance(email, str):
            raise GitHubOAuthError("verified_email_required")
        return GitHubIdentity(github_id=github_id, email=email)
