"""Buffer GraphQL integration for autonomous social posting.

Docs: https://developers.buffer.com/
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

BUFFER_API_URL = "https://api.buffer.com"


class BufferError(Exception):
    def __init__(self, message: str, payload: Any | None = None):
        self.payload = payload
        super().__init__(message)


def _graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    s = get_settings()
    if not s.buffer_api_token:
        raise BufferError("BUFFER_API_TOKEN not set")

    r = httpx.post(
        BUFFER_API_URL,
        headers={
            "Authorization": f"Bearer {s.buffer_api_token}",
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    try:
        payload = r.json()
    except ValueError as e:
        raise BufferError(f"Buffer returned non-JSON status {r.status_code}: {r.text[:500]}") from e

    if r.status_code >= 400 or payload.get("errors"):
        raise BufferError(f"Buffer GraphQL error status={r.status_code}", payload)
    return payload["data"]


def get_organizations() -> list[dict[str, Any]]:
    data = _graphql(
        """
        query GetOrganizations {
          account {
            organizations {
              id
              name
              ownerEmail
            }
          }
        }
        """
    )
    return data["account"]["organizations"]


def get_channels(organization_id: str) -> list[dict[str, Any]]:
    data = _graphql(
        """
        query GetChannels($organizationId: OrganizationId!) {
          channels(input: { organizationId: $organizationId }) {
            id
            name
            displayName
            service
            avatar
            isQueuePaused
          }
        }
        """,
        {"organizationId": organization_id},
    )
    return data["channels"]


def pick_channel_ids(channels: list[dict[str, Any]], *, services: list[str]) -> list[str]:
    wanted = {s.lower() for s in services}
    ids: list[str] = []
    for ch in channels:
        service = (ch.get("service") or "").lower()
        if service in wanted and not ch.get("isQueuePaused"):
            ids.append(ch["id"])
    return ids


def _organization_id() -> str:
    s = get_settings()
    if s.buffer_organization_id:
        return s.buffer_organization_id
    orgs = get_organizations()
    if not orgs:
        raise BufferError("No Buffer organizations found")
    return orgs[0]["id"]


def x_channel_ids() -> list[str]:
    s = get_settings()
    if s.buffer_x_channel_ids:
        return [ch.strip() for ch in s.buffer_x_channel_ids.split(",") if ch.strip()]
    channels = get_channels(_organization_id())
    return pick_channel_ids(channels, services=["twitter", "x"])


def create_post_mutation(*, channel_id: str, text: str) -> tuple[str, dict[str, Any]]:
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
            text
            dueAt
            channelId
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    variables = {
        "input": {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "addToQueue",
        }
    }
    return query, variables


def add_text_post_to_queue(*, channel_id: str, text: str) -> dict[str, Any]:
    query, variables = create_post_mutation(channel_id=channel_id, text=text)
    data = _graphql(query, variables)
    result = data["createPost"]
    if result.get("message"):
        raise BufferError(result["message"], result)
    return result["post"]
