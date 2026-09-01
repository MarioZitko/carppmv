"""HTTP layer for PPMV — thin by design. All logic lives in engine.py.

Domain exceptions (InvalidCO2Value, InvalidPriceValue,
UnsupportedVehicleCategory) are NOT caught here — they propagate to the
handlers registered in app/main.py via app.add_exception_handler(), which
map them to clean 4xx responses. Do not add try/except here; that would
duplicate the handler logic in two places.
"""

from fastapi import APIRouter

from app.ppmv.engine import WLTP_CUTOVER_DATE, calculate_ppmv
from app.ppmv.schemas import CO2Standard, PPMVRequest, PPMVResponse

router = APIRouter()


@router.post("/calculate", response_model=PPMVResponse)
async def calculate(request: PPMVRequest) -> PPMVResponse:
    breakdown = calculate_ppmv(
        price_eur=request.price_eur,
        co2_g_km=request.co2_g_km,
        fuel_type=request.fuel_type,
        first_registration_date=request.first_registration_date,
        declaration_date=request.declaration_date,
        eaer_city_range_km=request.eaer_city_range_km,
        seat_count=request.seat_count,
        is_camper=request.is_camper,
        is_new_vehicle=request.is_new_vehicle,
    )
    standard = CO2Standard.WLTP if request.first_registration_date >= WLTP_CUTOVER_DATE else CO2Standard.NEDC
    return PPMVResponse(breakdown=breakdown, co2_standard_used=standard)
