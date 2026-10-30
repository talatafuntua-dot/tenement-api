import secrets
import string
import uuid
import re

from sqlalchemy.exc import IntegrityError

from app.models import Property, LGCodeRegistry


def get_or_create_lg_code(db, property_record, prefix=None):
    """
    Allocate or retrieve a permanent LG Code.

    - Reuses an existing registry code.
    - Preserves an existing Property.lg_code.
    - Registers new codes in LGCodeRegistry.
    - Uses database uniqueness constraints to protect against duplicates.
    - Does not commit; the calling operation controls the transaction.
    """

    if property_record.id is None:
        db.flush()

    property_key = str(property_record.id)
    property_identifier = str(property_record.property_no)

    # Check possible existing registry key formats.
    registry = (
        db.query(LGCodeRegistry)
        .filter(
            (LGCodeRegistry.property_key == property_key)
            | (
                LGCodeRegistry.property_key
                == property_identifier
            )
            | (
                LGCodeRegistry.property_identifier
                == property_identifier
            )
        )
        .first()
    )

    if registry:
        property_record.lg_code = registry.lg_code
        db.flush()
        return registry.lg_code

    # Preserve an existing property code.
    if property_record.lg_code:
        lg_code = property_record.lg_code
    else:
        selected_prefix = (
            prefix
            or property_record.lg_prefix
            or "LG"
        )

        selected_prefix = selected_prefix.strip().upper()

        if not selected_prefix:
            selected_prefix = "LG"

        alphabet = string.ascii_uppercase + string.digits

        # Database uniqueness constraints are the final protection.
        for attempt in range(10):
            random_part = "".join(
                secrets.choice(alphabet)
                for _ in range(8)
            )

            lg_code = f"{selected_prefix}-{random_part}"

            try:
                with db.begin_nested():
                    property_record.lg_code = lg_code

                    registry = LGCodeRegistry(
                        property_key=property_key,
                        property_identifier=property_identifier,
                        prefix_used=selected_prefix,
                        lg_code=lg_code,
                    )

                    db.add(registry)
                    db.flush()

                return lg_code

            except IntegrityError:
                # Another request may have allocated this property.
                registry = (
                    db.query(LGCodeRegistry)
                    .filter(
                        LGCodeRegistry.property_key
                        == property_key
                    )
                    .first()
                )

                if registry:
                    property_record.lg_code = registry.lg_code
                    db.flush()
                    return registry.lg_code

                # Otherwise retry with a new random code.
                continue

        raise RuntimeError(
            "Unable to allocate a unique LG Code after 10 attempts."
        )

    # Existing Property.lg_code without a registry entry:
    # register it without replacing the code.
    try:
        with db.begin_nested():
            registry = LGCodeRegistry(
                property_key=property_key,
                property_identifier=property_identifier,
                prefix_used=(
                    prefix
                    or property_record.lg_prefix
                ),
                lg_code=lg_code,
            )

            db.add(registry)
            db.flush()

    except IntegrityError:
        registry = (
            db.query(LGCodeRegistry)
            .filter(
                LGCodeRegistry.property_key == property_key
            )
            .first()
        )

        if registry:
            property_record.lg_code = registry.lg_code
            db.flush()
            return registry.lg_code

        raise

    property_record.lg_code = lg_code
    db.flush()

    return lg_code


def allocate_bulk_lg_code(db, prefix=None, property_identifier=None):
    """
    Atomically allocate and permanently register a unique LG Code
    for an Excel bulk-generation row, without requiring a Property record.
    """

    selected_prefix = str(prefix or "LG").strip().upper()
    selected_prefix = re.sub(r"[^A-Z0-9_-]", "", selected_prefix)
    selected_prefix = selected_prefix[:41] or "LG"

    identifier = str(
        property_identifier or "Excel bulk allocation"
    ).strip()[:255]

    alphabet = string.ascii_uppercase + string.digits

    for attempt in range(20):
        random_part = "".join(
            secrets.choice(alphabet) for _ in range(8)
        )

        lg_code = f"{selected_prefix}-{random_part}"

        # A unique reservation key for this Excel allocation.
        property_key = f"BULK-{uuid.uuid4().hex}"

        try:
            # Reserve the code inside a database transaction.
            with db.begin_nested():
                registry = LGCodeRegistry(
                    property_key=property_key,
                    property_identifier=identifier,
                    prefix_used=selected_prefix,
                    lg_code=lg_code,
                )

                db.add(registry)
                db.flush()

            # Permanently commit the reservation.
            db.commit()

            return lg_code

        except IntegrityError:
            db.rollback()
            # The code or reservation key collided.
            # Try another randomly generated code.
            continue

    raise RuntimeError(
        "Unable to allocate a unique LG Code after 20 attempts."
    )

