import calendar
from datetime import date, datetime
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/availability", tags=["availability"])

@router.get("/calendar")
def get_labs_calendar(
    year: int = Query(..., ge=2024, le=2100),
    month: int = Query(..., ge=1, le=12),
    lab_id: int | None = Query(default=None),
):
    _, total_days = calendar.monthrange(year, month)
    
    result = []
    labs = [{"id": 1, "name": "Laboratorio de Redes"}, {"id": 2, "name": "Laboratorio de Sistemas"}]
    
    if lab_id:
        labs = [l for l in labs if l["id"] == lab_id]

    for lab in labs:
        days_out = []
        for day in range(1, total_days + 1):
            current_date = date(year, month, day)
            occupied_slots = (day % 4)
            
            if occupied_slots == 0:
                status = "available"
            elif occupied_slots >= 3:
                status = "occupied"
                occupied_slots = 3
            else:
                status = "partial"

            days_out.append({
                "day": day,
                "date": current_date.isoformat(),
                "status": status,
                "occupied_slots": occupied_slots,
                "total_slots": 3,
            })

        result.append({
            "laboratory_id": lab["id"],
            "laboratory_name": lab["name"],
            "year": year,
            "month": month,
            "days": days_out,
        })

    return result

@router.get("/day")
def get_day_reservations(
    date_value: str = Query(..., alias="date"),
    lab_id: int | None = Query(default=None),
):
    target_date = datetime.strptime(date_value, "%Y-%m-%d").date()
    
    labs = [{"id": 1, "name": "Laboratorio de Redes"}, {"id": 2, "name": "Laboratorio de Sistemas"}]
    if lab_id:
        labs = [l for l in labs if l["id"] == lab_id]

    result = []
    for lab in labs:
        result.append({
            "laboratory_id": lab["id"],
            "laboratory_name": lab["name"],
            "reservations": [
                {
                    "start_time": "08:00",
                    "end_time": "10:00",
                    "status": "occupied"
                }
            ]
        })

    return result
