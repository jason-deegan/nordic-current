"""Build a self-contained local HTML report from normalized project data."""

from __future__ import annotations

import csv
import html
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nordic_current.prices import AREA_EICS
from nordic_current.reservoirs import AREAS, CSV_COLUMNS as RESERVOIR_COLUMNS

PRICE_COLUMNS = ("area", "timestamp_utc", "price", "currency", "unit", "resolution")
REPORT_PATH = Path("data/processed/nordic_current_report.html")
PRICE_CSV_PATH = Path(
    "data/processed/entsoe_prices_NO1_20240101_20240101.csv"
)
RESERVOIR_CSV_PATH = Path("data/processed/nve_reservoirs.csv")
PRICE_DAY = date(2024, 1, 1)
AREAS_ORDERED = tuple(AREAS)


class VisualizationDataError(ValueError):
    """Raised when local normalized data are missing or invalid."""


@dataclass(frozen=True)
class ReservoirSeries:
    dates: tuple[date, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class PriceSeries:
    timestamps: tuple[datetime, ...]
    prices: tuple[float, ...]


def _read_csv(path: Path, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise VisualizationDataError(
            f"Required data file not found: {path}. "
            "Refresh the source data using the README commands, then try again."
        )
    try:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise VisualizationDataError(f"Data file has no header: {path}.")
            missing = sorted(set(required_columns) - set(reader.fieldnames))
            if missing:
                raise VisualizationDataError(
                    f"Data file {path} is missing columns: {', '.join(missing)}."
                )
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise VisualizationDataError(
            f"Could not read data file {path} ({type(error).__name__})."
        ) from None
    if not rows:
        raise VisualizationDataError(f"Data file contains no observations: {path}.")
    return rows


def load_reservoir_series(path: Path) -> dict[str, ReservoirSeries]:
    rows = _read_csv(path, RESERVOIR_COLUMNS)
    by_area: dict[str, list[tuple[date, float]]] = {area: [] for area in AREAS_ORDERED}
    seen: set[tuple[str, date]] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            area = row["area"]
            observed_date = date.fromisoformat(row["date"])
            fraction = float(row["filling_fraction"])
        except (TypeError, ValueError):
            raise VisualizationDataError(
                f"Reservoir CSV row {row_number} has an invalid area, date, or filling value."
            ) from None
        if area not in by_area:
            raise VisualizationDataError(
                f"Reservoir CSV row {row_number} has unsupported area {area!r}."
            )
        if not math.isfinite(fraction) or not 0 <= fraction <= 1.1:
            raise VisualizationDataError(
                f"Reservoir CSV row {row_number} has an implausible filling fraction."
            )
        key = (area, observed_date)
        if key in seen:
            raise VisualizationDataError(
                f"Reservoir data contains duplicate {area} record for {observed_date}."
            )
        seen.add(key)
        by_area[area].append((observed_date, fraction))

    series: dict[str, ReservoirSeries] = {}
    for area, observations in by_area.items():
        if not observations:
            raise VisualizationDataError(f"Reservoir data has no observations for {area}.")
        observations.sort(key=lambda item: item[0])
        if any(
            current[0] - previous[0] != timedelta(days=7)
            for previous, current in zip(observations, observations[1:])
        ):
            raise VisualizationDataError(
                f"Reservoir data for {area} has missing or irregular weekly dates."
            )
        dates, fractions = zip(*observations)
        series[area] = ReservoirSeries(
            dates=tuple(dates),
            values=tuple(fraction * 100 for fraction in fractions),
        )
    reference_dates = series[AREAS_ORDERED[0]].dates
    if any(item.dates != reference_dates for item in series.values()):
        raise VisualizationDataError(
            "Reservoir areas do not share the same weekly dates; "
            "the comparison chart requires aligned observations."
        )
    return series


def load_price_series(path: Path) -> PriceSeries:
    rows = _read_csv(path, PRICE_COLUMNS)
    observations: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            timestamp = datetime.fromisoformat(
                row["timestamp_utc"].replace("Z", "+00:00")
            )
            price = float(row["price"])
        except (TypeError, ValueError):
            raise VisualizationDataError(
                f"Price CSV row {row_number} has an invalid timestamp or price."
            ) from None
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise VisualizationDataError(
                f"Price CSV row {row_number} timestamp must include a timezone."
            )
        timestamp = timestamp.astimezone(timezone.utc)
        if row["area"] != "NO1":
            raise VisualizationDataError(
                f"Price CSV row {row_number} is not for bidding zone NO1."
            )
        if row["currency"] != "EUR" or row["unit"] != "MWH":
            raise VisualizationDataError(
                f"Price CSV row {row_number} must use EUR/MWh."
            )
        if row["resolution"] != "PT60M":
            raise VisualizationDataError(
                f"Price CSV row {row_number} is not hourly (PT60M)."
            )
        if not math.isfinite(price):
            raise VisualizationDataError(
                f"Price CSV row {row_number} has a non-finite price."
            )
        if timestamp in seen:
            raise VisualizationDataError(
                f"Price data contains a duplicate timestamp: {timestamp.isoformat()}."
            )
        seen.add(timestamp)
        observations.append((timestamp, price))

    observations.sort(key=lambda item: item[0])
    if len(observations) != 24:
        raise VisualizationDataError(
            f"The NO1 chart requires all 24 hourly observations for {PRICE_DAY}; "
            f"found {len(observations)}."
        )
    timestamps, prices = zip(*observations)
    expected_start = datetime(2023, 12, 31, 23, tzinfo=timezone.utc)
    if timestamps[0] != expected_start:
        raise VisualizationDataError(
            f"Price data does not begin at the validated UTC boundary "
            f"{expected_start.isoformat()} for {PRICE_DAY}."
        )
    if any(
        current - previous != timedelta(hours=1)
        for previous, current in zip(timestamps, timestamps[1:])
    ):
        raise VisualizationDataError(
            f"Price data for {PRICE_DAY} contains missing or irregular hourly observations."
        )
    return PriceSeries(tuple(timestamps), tuple(prices))


def _svg_polyline(
    values: tuple[float, ...],
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    left: float,
    top: float,
    width: float,
    height: float,
) -> str:
    points = []
    denominator_x = max(x_max - x_min, 1.0)
    denominator_y = max(y_max - y_min, 1.0)
    for index, value in enumerate(values):
        x = left + (index / denominator_x) * width
        y = top + ((y_max - value) / denominator_y) * height
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def render_reservoir_svg(series: dict[str, ReservoirSeries]) -> str:
    width, height = 1100, 520
    left, right, top, bottom = 78, 28, 28, 78
    plot_width, plot_height = width - left - right, height - top - bottom
    start = min(values.dates[0] for values in series.values())
    end = max(values.dates[-1] for values in series.values())
    span = max((end - start).days, 1)
    y_min, y_max = 0.0, 110.0
    pieces = [
        f'<svg id="reservoir-chart" class="chart" viewBox="0 0 {width} {height}" role="img" tabindex="0" '
        'aria-labelledby="reservoir-chart-title reservoir-chart-desc" '
        'xmlns="http://www.w3.org/2000/svg">',
        '<title id="reservoir-chart-title">Weekly reservoir filling in Norway</title>',
        '<desc id="reservoir-chart-desc">Filling fraction in percent for electricity areas NO1 through NO5.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for tick in range(0, 101, 20):
        y = top + ((y_max - tick) / (y_max - y_min)) * plot_height
        pieces.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
            'stroke="#e3e9ed" stroke-width="1"/>'
        )
        pieces.append(
            f'<text x="{left-12}" y="{y+4:.2f}" text-anchor="end" '
            f'class="axis-label">{tick}%</text>'
        )

    first_year = (start.year // 5) * 5
    for year in range(first_year, end.year + 1, 5):
        tick_date = date(year, 1, 1)
        if not start <= tick_date <= end:
            continue
        x = left + ((tick_date - start).days / span) * plot_width
        pieces.extend(
            (
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" '
                'stroke="#f0f3f5" stroke-width="1"/>',
                f'<text x="{x:.2f}" y="{height-bottom+25}" text-anchor="middle" '
                f'class="axis-label">{year}</text>',
            )
        )

    colors = {
        "NO1": "#007f86",
        "NO2": "#d17a00",
        "NO3": "#5356a6",
        "NO4": "#bd4961",
        "NO5": "#378044",
    }
    for area in AREAS_ORDERED:
        area_series = series[area]
        points = []
        for observed_date, value in zip(area_series.dates, area_series.values):
            x = left + ((observed_date - start).days / span) * plot_width
            y = top + ((y_max - value) / (y_max - y_min)) * plot_height
            points.append(f"{x:.2f},{y:.2f}")
        pieces.append(
            f'<polyline fill="none" stroke="{colors[area]}" stroke-width="1.7" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity="0.9" '
            f'points="{" ".join(points)}">'
            f'<title>{area}: weekly reservoir filling</title></polyline>'
        )
    pieces.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#52616b"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" '
            f'y2="{height-bottom}" stroke="#52616b"/>',
            f'<text x="{width/2}" y="{height-16}" text-anchor="middle" '
            'class="axis-title">Observation date (weekly)</text>',
            f'<text transform="translate(20 {height/2}) rotate(-90)" '
            'text-anchor="middle" class="axis-title">Reservoir filling (%)</text>',
            "</svg>",
        )
    )
    return "\n".join(pieces)


def render_price_svg(series: PriceSeries) -> str:
    width, height = 1100, 440
    left, right, top, bottom = 78, 28, 28, 72
    plot_width, plot_height = width - left - right, height - top - bottom
    low = min(series.prices)
    high = max(series.prices)
    spread = high - low
    padding = max(spread * 0.12, 5.0)
    y_min = math.floor((low - padding) / 10) * 10
    y_max = math.ceil((high + padding) / 10) * 10
    if y_min == y_max:
        y_min -= 10
        y_max += 10
    pieces = [
        f'<svg id="price-chart" class="chart" viewBox="0 0 {width} {height}" role="img" tabindex="0" '
        'aria-labelledby="price-chart-title price-chart-desc" '
        'xmlns="http://www.w3.org/2000/svg">',
        '<title id="price-chart-title">NO1 hourly day-ahead electricity prices</title>',
        '<desc id="price-chart-desc">Twenty-four hourly prices for Norwegian market date 1 January 2024, in euros per megawatt-hour.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    tick_step = max(10, math.ceil((y_max - y_min) / 5 / 10) * 10)
    tick = math.ceil(y_min / tick_step) * tick_step
    while tick <= y_max:
        y = top + ((y_max - tick) / (y_max - y_min)) * plot_height
        pieces.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
                'stroke="#e3e9ed" stroke-width="1"/>',
                f'<text x="{left-12}" y="{y+4:.2f}" text-anchor="end" '
                f'class="axis-label">€{tick}</text>',
            )
        )
        tick += tick_step

    for hour in range(0, 24, 3):
        x = left + (hour / 23) * plot_width
        pieces.extend(
            (
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" '
                'stroke="#f0f3f5" stroke-width="1"/>',
                f'<text x="{x:.2f}" y="{height-bottom+24}" text-anchor="middle" '
                f'class="axis-label">{hour:02d}:00</text>',
            )
        )
    points = _svg_polyline(
        series.prices,
        x_min=0,
        x_max=len(series.prices) - 1,
        y_min=y_min,
        y_max=y_max,
        left=left,
        top=top,
        width=plot_width,
        height=plot_height,
    )
    pieces.append(
        f'<polyline fill="none" stroke="#174d7a" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{points}"/>'
    )
    for hour, (timestamp, price) in enumerate(zip(series.timestamps, series.prices)):
        x = left + (hour / 23) * plot_width
        y = top + ((y_max - price) / (y_max - y_min)) * plot_height
        title = html.escape(f"Market hour {hour:02d}:00 — €{price:.2f}/MWh")
        pieces.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.4" fill="#174d7a">'
            f"<title>{title}; UTC {timestamp.isoformat()}</title></circle>"
        )
    pieces.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#52616b"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" '
            f'y2="{height-bottom}" stroke="#52616b"/>',
            f'<text x="{width/2}" y="{height-14}" text-anchor="middle" '
            'class="axis-title">Market hour (Europe/Oslo, 1 January 2024)</text>',
            f'<text transform="translate(20 {height/2}) rotate(-90)" '
            'text-anchor="middle" class="axis-title">Day-ahead price (EUR/MWh)</text>',
            "</svg>",
        )
    )
    return "\n".join(pieces)


INTERACTION_SCRIPT = r"""
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  const colors = {NO1:"#087f83",NO2:"#d28a16",NO3:"#6261b5",NO4:"#cf5367",NO5:"#43874c"};
  const ns = "http://www.w3.org/2000/svg";
  const reservoirSvg = document.getElementById("reservoir-chart");
  const reservoirTip = document.getElementById("reservoir-tooltip");
  const priceSvg = document.getElementById("price-chart");
  const priceTip = document.getElementById("price-tooltip");
  const frame = {width:1100,height:520,left:78,right:28,top:28,bottom:78};
  const plotW = frame.width-frame.left-frame.right;
  const plotH = frame.height-frame.top-frame.bottom;
  let range = "all";

  function svgNode(name, attributes, text) {
    const item = document.createElementNS(ns, name);
    Object.entries(attributes || {}).forEach(([key,value]) => item.setAttribute(key,value));
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function appendLine(svg,x1,y1,x2,y2,color) {
    svg.append(svgNode("line",{x1,y1,x2,y2,stroke:color,"stroke-width":1}));
  }
  function appendText(svg,x,y,text,anchor="middle") {
    svg.append(svgNode("text",{x,y,"text-anchor":anchor,class:"axis-label"},text));
  }
  function dayMillis(value) { return Date.parse(value+"T00:00:00Z"); }
  function selectedAreas() {
    return [...document.querySelectorAll("[data-area-toggle]:checked")].map(item=>item.value);
  }
  function selectedDates() {
    const end = dayMillis(data.end);
    if (range === "all") return dayMillis(data.start);
    const start = new Date(end);
    start.setUTCFullYear(start.getUTCFullYear()-(range === "5y" ? 5 : 10));
    return Math.max(dayMillis(data.start),start.getTime());
  }
  function renderReservoir() {
    const start = selectedDates(), end = dayMillis(data.end);
    const span = Math.max(end-start,1);
    const active = selectedAreas();
    reservoirSvg.replaceChildren();
    reservoirSvg.setAttribute("viewBox",`0 0 ${frame.width} ${frame.height}`);
    reservoirSvg.append(svgNode("title",{id:"reservoir-chart-title"},"Weekly reservoir filling by electricity area"));
    reservoirSvg.append(svgNode("desc",{id:"reservoir-chart-desc"},"Interactive weekly reservoir filling percentages for NO1 through NO5."));
    reservoirSvg.append(svgNode("rect",{width:"100%",height:"100%",fill:"#fff"}));
    for (let tick=0;tick<=100;tick+=20) {
      const y=frame.top+(110-tick)/110*plotH;
      appendLine(reservoirSvg,frame.left,y,frame.width-frame.right,y,"#e4eaec");
      appendText(reservoirSvg,frame.left-12,y+4,`${tick}%`,"end");
    }
    const yearStep=range==="all"?5:(range==="10y"?2:1);
    let year=Math.ceil(new Date(start).getUTCFullYear()/yearStep)*yearStep;
    for (;year<=new Date(end).getUTCFullYear();year+=yearStep) {
      const x=frame.left+(Date.UTC(year,0,1)-start)/span*plotW;
      if (x<frame.left || x>frame.width-frame.right) continue;
      appendLine(reservoirSvg,x,frame.top,x,frame.height-frame.bottom,"#eff2f3");
      appendText(reservoirSvg,x,frame.height-frame.bottom+25,String(year));
    }
    for (const area of data.areas) {
      if (!active.includes(area)) continue;
      const series=data.series[area], points=[];
      series.dates.forEach((day,index)=>{
        const stamp=dayMillis(day);
        if (stamp<start || stamp>end) return;
        const x=frame.left+(stamp-start)/span*plotW;
        const y=frame.top+(110-series.values[index])/110*plotH;
        points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
      });
      reservoirSvg.append(svgNode("polyline",{
        fill:"none",stroke:colors[area],"stroke-width":2.1,
        "stroke-linejoin":"round","stroke-linecap":"round",points:points.join(" ")
      }));
    }
    appendLine(reservoirSvg,frame.left,frame.top,frame.left,frame.height-frame.bottom,"#60737c");
    appendLine(reservoirSvg,frame.left,frame.height-frame.bottom,frame.width-frame.right,frame.height-frame.bottom,"#60737c");
    appendText(reservoirSvg,frame.width/2,frame.height-16,"Observation date (weekly)");
    reservoirSvg.append(svgNode("text",{transform:`translate(20 ${frame.height/2}) rotate(-90)`,"text-anchor":"middle",class:"axis-title"},"Reservoir filling (%)"));
  }
  function nearestIndex(dates, stamp) {
    let low=0,high=dates.length-1;
    while (low<high) {
      const mid=Math.floor((low+high)/2);
      if (dayMillis(dates[mid])<stamp) low=mid+1; else high=mid;
    }
    if (low>0 && stamp-dayMillis(dates[low-1])<=dayMillis(dates[low])-stamp) return low-1;
    return low;
  }
  function showReservoirAt(clientX) {
    const box=reservoirSvg.getBoundingClientRect();
    const viewX=(clientX-box.left)/box.width*frame.width;
    const ratio=Math.max(0,Math.min(1,(viewX-frame.left)/plotW));
    const start=selectedDates(), end=dayMillis(data.end);
    const target=start+ratio*(end-start);
    const index=nearestIndex(data.series.NO1.dates,target);
    reservoirTip.dataset.index=String(index);
    const day=data.series.NO1.dates[index];
    const rows=selectedAreas().map(area=>{
      const values=data.series[area].values;
      return `<span style="color:${colors[area]}"><b>${area}</b> ${values[index].toFixed(1)}%</span>`;
    }).join(" · ");
    reservoirTip.innerHTML=`<strong>${day}</strong><span>${rows || "Select an area to inspect its value."}</span>`;
  }
  function renderPriceInteraction() {
    const x0=78,x1=1072,top=28,bottom=368;
    const crosshair=svgNode("line",{id:"price-crosshair",y1:top,y2:bottom,stroke:"#183e53","stroke-dasharray":"4 4","stroke-width":1.5,visibility:"hidden"});
    const marker=svgNode("circle",{id:"price-focus-marker",r:6,fill:"#fff",stroke:"#174d7a","stroke-width":3,visibility:"hidden"});
    priceSvg.append(crosshair,marker);
    function showPriceAt(index) {
      const x=x0+(index/(data.prices.length-1))*(x1-x0);
      const y=data.priceY[index];
      crosshair.setAttribute("x1",x); crosshair.setAttribute("x2",x);
      crosshair.setAttribute("visibility","visible");
      marker.setAttribute("cx",x); marker.setAttribute("cy",y); marker.setAttribute("visibility","visible");
      const stamp=data.prices[index];
      const localTime=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Oslo",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(stamp.utc));
      priceTip.innerHTML=`<strong>${localTime} Europe/Oslo · €${stamp.value.toFixed(2)}/MWh</strong><span>UTC ${stamp.utc}</span>`;
      priceTip.dataset.index=String(index);
    }
    priceSvg.addEventListener("pointermove",event=>{
      const box=priceSvg.getBoundingClientRect();
      const viewX=(event.clientX-box.left)/box.width*1100;
      const ratio=Math.max(0,Math.min(1,(viewX-x0)/(x1-x0)));
      const index=Math.round(ratio*(data.prices.length-1));
      showPriceAt(index);
    });
    priceSvg.addEventListener("pointerleave",()=>{
      crosshair.setAttribute("visibility","hidden"); marker.setAttribute("visibility","hidden");
    });
    priceSvg.addEventListener("keydown",event=>{
      if (!["ArrowLeft","ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const current=priceTip.dataset.index ? Number(priceTip.dataset.index) : data.prices.length-1;
      const next=Math.max(0,Math.min(data.prices.length-1,current+(event.key==="ArrowRight"?1:-1)));
      showPriceAt(next);
    });
  }
  document.querySelectorAll("[data-range]").forEach(button=>button.addEventListener("click",()=>{
    range=button.dataset.range;
    document.querySelectorAll("[data-range]").forEach(item=>{
      const selected=item===button;
      item.classList.toggle("selected",selected);
      item.setAttribute("aria-pressed",String(selected));
    });
    renderReservoir();
  }));
  document.querySelectorAll("[data-area-toggle]").forEach(toggle=>toggle.addEventListener("change",renderReservoir));
  reservoirSvg.addEventListener("pointermove",event=>showReservoirAt(event.clientX));
  reservoirSvg.addEventListener("pointerleave",()=>{ reservoirTip.innerHTML="<span>Hover or focus the chart to inspect a week.</span>"; });
  reservoirSvg.addEventListener("keydown",event=>{
    if (!["ArrowLeft","ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const dates=data.series.NO1.dates;
    const current=reservoirTip.dataset.index ? Number(reservoirTip.dataset.index) : dates.length-1;
    const next=Math.max(0,Math.min(dates.length-1,current+(event.key==="ArrowRight"?1:-1)));
    reservoirTip.dataset.index=String(next);
    const ratio=(dayMillis(dates[next])-selectedDates())/Math.max(dayMillis(data.end)-selectedDates(),1);
    const clientX=reservoirSvg.getBoundingClientRect().left+reservoirSvg.getBoundingClientRect().width*(frame.left+ratio*plotW)/frame.width;
    showReservoirAt(clientX);
  });
  renderReservoir();
  renderPriceInteraction();
})();
"""


def _chart_data(
    reservoirs: dict[str, ReservoirSeries],
    prices: PriceSeries,
) -> str:
    payload = {
        "start": min(series.dates[0] for series in reservoirs.values()).isoformat(),
        "end": max(series.dates[-1] for series in reservoirs.values()).isoformat(),
        "areas": list(AREAS_ORDERED),
        "series": {
            area: {
                "dates": [day.isoformat() for day in series.dates],
                "values": series.values,
            }
            for area, series in reservoirs.items()
        },
        "prices": [
            {
                "utc": timestamp.isoformat().replace("+00:00", "Z"),
                "value": value,
            }
            for timestamp, value in zip(prices.timestamps, prices.prices)
        ],
        "priceY": _price_plot_y(prices),
    }
    return json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")


def _price_plot_y(series: PriceSeries) -> list[float]:
    low, high = min(series.prices), max(series.prices)
    padding = max((high - low) * 0.12, 5.0)
    y_min = math.floor((low - padding) / 10) * 10
    y_max = math.ceil((high + padding) / 10) * 10
    if y_min == y_max:
        y_min -= 10
        y_max += 10
    return [28 + (y_max - price) / (y_max - y_min) * 340 for price in series.prices]


def render_html(
    reservoirs: dict[str, ReservoirSeries],
    prices: PriceSeries,
    *,
    price_source_period_start: str = "2023-12-31T23:00:00Z",
    price_source_period_end: str = "2024-01-01T23:00:00Z",
) -> str:
    start = min(series.dates[0] for series in reservoirs.values())
    end = max(series.dates[-1] for series in reservoirs.values())
    latest = max(series.dates[-1] for series in reservoirs.values())
    latest_values = [
        f'<div class="area-stat"><span class="dot" style="--area:{color}"></span>'
        f'<span class="area-name">{area}</span><strong>{reservoirs[area].values[-1]:.1f}%</strong></div>'
        for area, color in (
            ("NO1", "#087f83"), ("NO2", "#d28a16"), ("NO3", "#6261b5"),
            ("NO4", "#cf5367"), ("NO5", "#43874c"),
        )
    ]
    lowest, highest = min(prices.prices), max(prices.prices)
    average = sum(prices.prices) / len(prices.prices)
    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#102f3c">
  <title>Nordic Current — Norwegian power &amp; reservoirs</title>
  <style>
    :root {{ color-scheme: light; --ink:#172f3b; --muted:#62747b; --paper:#f3f5f2; --line:#dbe2df; --teal:#087f83; --navy:#102f3c; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 Inter, "Segoe UI", system-ui, sans-serif; }}
    main {{ width:min(1240px,calc(100% - 40px)); margin:24px auto 60px; }}
    .hero {{ position:relative; overflow:hidden; padding:42px 46px; color:#fff; background:var(--navy); border-radius:22px; }}
    .hero:after {{ position:absolute; right:-115px; top:-190px; width:520px; height:520px; border:1px solid #86d2c733; border-radius:50%; box-shadow:0 0 0 42px #86d2c711,0 0 0 84px #86d2c709; content:""; pointer-events:none; }}
    .hero-inner {{ position:relative; z-index:1; max-width:820px; }}
    .eyebrow {{ margin:0 0 8px; color:#77c7bd; font-size:.75rem; font-weight:750; letter-spacing:.15em; text-transform:uppercase; }}
    h1 {{ max-width:760px; margin:0; font-size:clamp(2.4rem,6vw,4.8rem); line-height:1.02; letter-spacing:-.055em; }}
    .hero-copy {{ max-width:670px; margin:20px 0 0; color:#d5e2e2; font-size:1.05rem; }}
    .topline {{ display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:36px; }}
    .brand {{ font-size:.86rem; font-weight:700; letter-spacing:.04em; }}
    .live-label {{ display:flex; align-items:center; gap:8px; color:#c6dddd; font-size:.82rem; }}
    .live-dot {{ width:8px; height:8px; background:#80d2a8; border-radius:50%; box-shadow:0 0 0 4px #80d2a822; }}
    nav {{ display:flex; gap:20px; margin-top:25px; }}
    nav a {{ color:#b9d3d3; font-size:.9rem; text-decoration:none; }}
    nav a:hover,nav a:focus-visible {{ color:#fff; text-decoration:underline; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0 24px; }}
    .metric {{ padding:16px 18px; background:#fff; border:1px solid var(--line); border-radius:13px; }}
    .metric-label {{ display:block; color:var(--muted); font-size:.76rem; font-weight:650; letter-spacing:.04em; text-transform:uppercase; }}
    .metric-value {{ display:block; margin-top:4px; font-size:1.28rem; font-weight:750; letter-spacing:-.03em; }}
    .metric-note {{ display:block; color:var(--muted); font-size:.78rem; }}
    .section {{ margin-top:18px; padding:27px 30px 25px; background:#fff; border:1px solid var(--line); border-radius:17px; box-shadow:0 8px 28px #102f3c08; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:20px; }}
    h2 {{ margin:0; font-size:1.45rem; letter-spacing:-.03em; }}
    h3 {{ margin:0; font-size:1.03rem; }}
    .deck {{ max-width:780px; margin:7px 0 0; color:var(--muted); }}
    .controls {{ display:flex; flex-wrap:wrap; align-items:center; gap:7px; }}
    .control-label {{ margin-right:5px; color:var(--muted); font-size:.78rem; font-weight:650; }}
    button {{ padding:8px 12px; color:#40545e; background:#f4f6f4; border:1px solid #dfe6e2; border-radius:8px; font:inherit; font-size:.82rem; cursor:pointer; }}
    button:hover {{ border-color:#94b6b0; }}
    button:focus-visible,input:focus-visible,svg:focus-visible,a:focus-visible {{ outline:3px solid #80cfc1; outline-offset:3px; }}
    button.selected {{ color:#fff; background:var(--navy); border-color:var(--navy); }}
    .area-controls {{ display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:17px; }}
    .area-toggle {{ display:inline-flex; align-items:center; gap:7px; color:#344b55; font-size:.86rem; cursor:pointer; }}
    .area-toggle input {{ accent-color:var(--area); width:15px; height:15px; }}
    .area-toggle .dot,.area-stat .dot {{ width:9px; height:9px; background:var(--area); border-radius:50%; }}
    .chart {{ display:block; width:100%; height:auto; margin:14px 0 0; overflow:visible; touch-action:pan-y; }}
    .axis-label {{ fill:#62747b; font:12px system-ui,sans-serif; }}
    .axis-title {{ fill:#324c57; font:13px system-ui,sans-serif; font-weight:650; }}
    .tooltip {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px; min-height:44px; margin-top:4px; padding:10px 13px; color:#324a54; background:#f4f7f5; border:1px solid #e2e9e5; border-radius:9px; font-size:.85rem; }}
    .tooltip strong {{ color:var(--ink); }}
    .area-snapshot {{ display:grid; grid-template-columns:repeat(5,1fr); gap:9px; margin:12px 0 2px; }}
    .area-stat {{ display:flex; align-items:center; gap:8px; padding:11px 12px; background:#f7f8f6; border-radius:9px; }}
    .area-name {{ color:var(--muted); font-size:.82rem; }}
    .area-stat strong {{ margin-left:auto; font-size:.97rem; }}
    .source {{ margin:13px 0 0; color:var(--muted); font-size:.83rem; }}
    .source a {{ color:#17676b; }}
    .notice {{ margin-top:15px; padding:13px 15px; color:#604617; background:#fff7e8; border:1px solid #f0dfbc; border-left:4px solid #d28a16; border-radius:8px; font-size:.88rem; }}
    .method {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .method p {{ margin:7px 0 0; color:var(--muted); }}
    .footer {{ margin:20px 4px; color:var(--muted); font-size:.82rem; }}
    @media(max-width:800px) {{ .metrics {{ grid-template-columns:repeat(2,1fr); }} .section-head {{ flex-direction:column; }} .area-snapshot {{ grid-template-columns:repeat(3,1fr); }} }}
    @media(max-width:560px) {{ main {{ width:calc(100% - 18px); margin:9px auto 30px; }} .hero {{ padding:24px 20px; border-radius:15px; }} .topline {{ margin-bottom:34px; }} .section {{ padding:19px 13px; border-radius:13px; }} .metrics {{ gap:8px; }} .metric {{ padding:12px; }} .metric-value {{ font-size:1.1rem; }} .area-snapshot {{ grid-template-columns:repeat(2,1fr); }} .method {{ grid-template-columns:1fr; }} .axis-label {{ font-size:10px; }} nav {{ gap:14px; }} }}
    @media(prefers-reduced-motion:reduce) {{ html {{ scroll-behavior:auto; }} * {{ animation-duration:.01ms !important; transition-duration:.01ms !important; }} }}
  </style>
</head>
<body>
<main>
  <header class="hero">
    <div class="topline"><span class="brand">NORDIC CURRENT <span aria-hidden="true">/</span> FIELD NOTES 01</span><span class="live-label"><span class="live-dot"></span>PUBLIC DATA · TWO SOURCES</span></div>
    <div class="hero-inner">
      <p class="eyebrow">A personal energy-data project</p>
      <h1>Norway’s water reserve,<br>in a changing power system.</h1>
      <p class="hero-copy">Weekly reservoir filling across five electricity areas, alongside one carefully checked day of NO1 day-ahead prices. Explore each dataset on its own; their time coverage is not comparable.</p>
      <nav aria-label="Report sections"><a href="#reservoirs">Reservoirs</a><a href="#prices">NO1 prices</a><a href="#method">Sources &amp; limits</a></nav>
    </div>
  </header>
  <section class="metrics" aria-label="Dataset overview">
    <div class="metric"><span class="metric-label">Reservoir history</span><strong class="metric-value">{start.year}–{end.year}</strong><span class="metric-note">Weekly · five areas</span></div>
    <div class="metric"><span class="metric-label">Latest reservoir snapshot</span><strong class="metric-value">{latest.isoformat()}</strong><span class="metric-note">NVE observation date</span></div>
    <div class="metric"><span class="metric-label">NO1 price sample</span><strong class="metric-value">24 hours</strong><span class="metric-note">1 January 2024 · hourly</span></div>
    <div class="metric"><span class="metric-label">Price range</span><strong class="metric-value">€{lowest:.2f}–€{highest:.2f}</strong><span class="metric-note">EUR/MWh · sample min/max</span></div>
  </section>
  <section class="section" id="reservoirs" aria-labelledby="reservoir-heading">
    <div class="section-head"><div><p class="eyebrow">01 / Hydropower storage</p><h2 id="reservoir-heading">Reservoir filling across Norway</h2><p class="deck">Weekly filling as a share of each area’s reservoir capacity. Change the time window or switch areas on and off to compare their seasonal patterns.</p></div>
      <div class="controls" role="group" aria-label="Reservoir chart date range"><span class="control-label">WINDOW</span><button type="button" data-range="5y" aria-pressed="false">5 years</button><button type="button" data-range="10y" aria-pressed="false">10 years</button><button type="button" data-range="all" class="selected" aria-pressed="true">All history</button></div>
    </div>
    <div class="area-controls" role="group" aria-label="Toggle electricity areas">
      {''.join(f'<label class="area-toggle" style="--area:{color}"><input type="checkbox" data-area-toggle value="{area}" checked><span class="dot"></span>{area}</label>' for area,color in (("NO1","#087f83"),("NO2","#d28a16"),("NO3","#6261b5"),("NO4","#cf5367"),("NO5","#43874c")))}
    </div>
    {render_reservoir_svg(reservoirs)}
    <div id="reservoir-tooltip" class="tooltip" role="status" aria-live="polite"><span>Hover the chart to inspect a week; use the arrow keys when the chart is focused.</span></div>
    <div class="area-snapshot" aria-label="Latest reservoir filling by area">{''.join(latest_values)}</div>
    <p class="source">Source: <a href="https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData">NVE Magasinstatikk API</a>. Weekly snapshot coverage: {start.isoformat()}–{end.isoformat()}. NVE identifies the data as NLOD, compatible with CC BY 3.0 Norway; attribution is required. The series summarizes monitored reservoirs, not every Norwegian reservoir.</p>
  </section>
  <section class="section" id="prices" aria-labelledby="price-heading">
    <p class="eyebrow">02 / Day-ahead market · NO1</p>
    <h2 id="price-heading">One market day, hour by hour</h2>
    <p class="deck">The 1 January 2024 NO1 sample. Hover or focus the chart to inspect each hourly price.</p>
    {render_price_svg(prices)}
    <div id="price-tooltip" class="tooltip" role="status" aria-live="polite"><span>Hover the chart to inspect a market hour.</span></div>
    <p class="source">Source: <a href="https://transparency.entsoe.eu/">ENTSO-E Transparency Platform</a>, day-ahead prices (A44), NO1 ({AREA_EICS["NO1"]}). 24 observations · PT60M · EUR/MWh. Returned interval: {html.escape(price_source_period_start)}–{html.escape(price_source_period_end)} UTC. One day and one area have been live-validated; this does not establish broader coverage or validate other areas.</p>
    <p class="notice"><strong>Local-use data.</strong> Applicable ENTSO-E reuse terms have not been confirmed. This HTML contains price observations and a derived chart; keep it local and do not publish or redistribute it until those terms are checked.</p>
  </section>
  <section class="section method" id="method" aria-label="Method and limitations">
    <div><p class="eyebrow">Sources &amp; method</p><h3>Two feeds, kept distinct</h3><p>Reservoir filling is weekly; prices are hourly for one market date. The plots use different time spans, are not joined, and do not support a causal or correlational claim. A future comparison would require an explicit time aggregation and common validated coverage.</p></div>
    <div><p class="eyebrow">Reproducible locally</p><h3>Built from validated CSVs</h3><p>Generated from local NVE and ENTSO-E outputs using Python’s standard library. No external chart service, JavaScript library, credentials, or network connection is needed to open this report. Generated HTML and price data remain excluded from Git.</p></div>
  </section>
  <footer class="footer">NORDIC CURRENT · Personal demonstration project · Source timestamps retained in UTC</footer>
</main>
<script id="chart-data" type="application/json">{_chart_data(reservoirs,prices)}</script>
<script>{INTERACTION_SCRIPT}</script>
</body>
</html>
"""
    return report


def build_report(
    project_root: Path,
    *,
    reservoir_csv: Path | None = None,
    price_csv: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    root = project_root.resolve()
    reservoir_path = reservoir_csv or root / RESERVOIR_CSV_PATH
    price_path = price_csv or root / PRICE_CSV_PATH
    report_path = output_path or root / REPORT_PATH
    reservoir_series = load_reservoir_series(reservoir_path)
    price_series = load_price_series(price_path)
    markup = render_html(reservoir_series, price_series)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(markup, encoding="utf-8", newline="\n")
        os.replace(temporary, report_path)
    except OSError as error:
        raise VisualizationDataError(
            f"Could not write HTML report ({type(error).__name__})."
        ) from None
    return report_path
