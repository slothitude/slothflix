"""Token service for auth token management."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from slothflix.models.models import Token


class TokenService:
    @staticmethod
    async def create(session, user_id: str, username: str, token: str, expires_at: str):
        """Create a new auth token, revoking old ones for the user."""
        now = datetime.now(timezone.utc).isoformat()

        # Revoke old tokens
        await session.execute(
            update(Token)
            .where(Token.user_id == str(user_id))
            .values(revoked=1)
        )

        # Insert new token
        db_token = Token(
            user_id=str(user_id),
            username=username,
            token=token,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(db_token)
        await session.commit()

    @staticmethod
    async def validate(session, token_str: str) -> Token | None:
        """Validate a token and return it if valid (not expired, not revoked)."""
        now = datetime.now(timezone.utc).isoformat()
        result = await session.execute(
            select(Token).where(
                Token.token == token_str,
                Token.revoked == 0,
                Token.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke(session, token_str: str = None, user_id: str = None):
        """Revoke token(s) by token string or user_id."""
        if token_str:
            await session.execute(
                update(Token).where(Token.token == token_str).values(revoked=1)
            )
        elif user_id:
            await session.execute(
                update(Token).where(Token.user_id == str(user_id)).values(revoked=1)
            )
        await session.commit()

    @staticmethod
    async def get_user_token(session, user_id: str) -> Token | None:
        """Get the active token for a user."""
        now = datetime.now(timezone.utc).isoformat()
        result = await session.execute(
            select(Token)
            .where(
                Token.user_id == str(user_id),
                Token.revoked == 0,
                Token.expires_at > now,
            )
            .order_by(Token.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def generate_token() -> str:
        """Generate a random token."""
        import secrets

        return secrets.token_hex(16)

    @staticmethod
    def expiry_days(days: int) -> str:
        """Get ISO format expiry timestamp."""
        return (
            datetime.now(timezone.utc) + timedelta(days=days)
        ).isoformat()
