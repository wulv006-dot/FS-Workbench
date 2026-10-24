"""Strict normalized types: source mappings must be verified by the integrator."""
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation


class ContractError(ValueError):
    pass


def identity(value):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise ContractError('INVALID_IDENTITY')
    return value


def source_identity(value):
    if type(value) not in (str, int):
        raise ContractError('INVALID_IDENTITY')
    return identity(str(value))


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ContractError('TIMEZONE_REQUIRED') from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False)
    except (TypeError, ValueError):
        raise ContractError('INVALID_CANONICAL_PAYLOAD') from None


@dataclass(frozen=True)
class Money:
    currency: str
    scale: int
    minor: int

    def __post_init__(self):
        if (not isinstance(self.currency, str) or len(self.currency) != 3
                or not self.currency.isascii() or not self.currency.isalpha()
                or self.currency != self.currency.upper()
                or type(self.scale) is not int or not 0 <= self.scale <= 6
                or type(self.minor) is not int or not 0 <= self.minor <= 9223372036854775807):
            raise ContractError('INVALID_MONEY')

    @classmethod
    def parse(cls, value, currency, scales):
        # Floats and formatted amounts are rejected; exact source units are contractual.
        if (currency not in scales or not isinstance(value, (str, int)) or isinstance(value, bool)
                or len(str(value)) > 128):
            raise ContractError('MONEY_MAPPING_REQUIRED')
        scale = scales[currency]
        if type(scale) is not int or not 0 <= scale <= 6:
            raise ContractError('MONEY_MAPPING_REQUIRED')
        try:
            number = Decimal(value)
            if not number.is_finite() or number < 0:
                raise ValueError()
            parts = number.as_tuple()
            coefficient = int(''.join(str(digit) for digit in parts.digits))
            shift = parts.exponent + scale
            if not coefficient:
                minor = 0
            elif shift >= 0:
                if len(parts.digits) + shift > 19:
                    raise ValueError()
                minor = coefficient * 10 ** shift
            else:
                if -shift > len(parts.digits):
                    raise ValueError()
                minor, remainder = divmod(coefficient, 10 ** -shift)
                if remainder:
                    raise ValueError()
            return cls(currency, scale, minor)
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            raise ContractError('INVALID_MONEY') from None


def same_money(left, right):
    if (left.currency, left.scale) != (right.currency, right.scale):
        raise ContractError('CURRENCY_OR_SCALE_CONFLICT')
