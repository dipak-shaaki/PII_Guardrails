import logging

from pydantic import BaseModel, Field

from pii_shield.agent.tools import Tool, ToolRegistry

logger = logging.getLogger(__name__)


class SendEmailArgs(BaseModel):
    to_email: str = Field(description="Recipient email address")
    subject: str
    body: str


class BookCallbackArgs(BaseModel):
    name: str = Field(description="Customer's full name")
    phone: str = Field(description="Customer's phone number")
    preferred_time: str = Field(description="When the customer wants the call")


async def send_confirmation_email(args: SendEmailArgs) -> dict:
    # A real integration (SMTP / email API) goes here. It receives REAL values.
    logger.info("Confirmation email dispatched")  # never log the recipient
    return {"status": "sent", "to": args.to_email}


async def book_callback(args: BookCallbackArgs) -> dict:
    logger.info("Callback booked")
    return {
        "status": "booked",
        "name": args.name,
        "phone": args.phone,
        "time": args.preferred_time,
    }


def demo_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "send_confirmation_email",
                "Send a confirmation email to the customer.",
                SendEmailArgs,
                send_confirmation_email,
            ),
            Tool(
                "book_callback",
                "Book a callback from a support agent.",
                BookCallbackArgs,
                book_callback,
            ),
        ]
    )
