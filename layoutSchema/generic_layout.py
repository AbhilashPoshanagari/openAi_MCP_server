from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class MapCenter(BaseModel):
    center: List[float] = Field(..., title="Map center")

class MapZoom(BaseModel):
    zoom: int = Field(..., title="Zoom")

class FeatureStyle(BaseModel):
    color: Optional[str] = Field(None, title="Stroke Color")
    fillColor: Optional[str] = Field(None, title="Fill Color")
    radius: Optional[int] = Field(None, title="Point Radius")
    fillOpacity: Optional[float] = Field(None, title="Fill Opacity")


class MapFeature(BaseModel):
    id: str = Field(..., title="ID")
    name: str = Field(..., title="Name")
    type: str = Field(..., title="Feature Type")
    coordinates: List[float] = Field(
        ..., 
        title="Coordinates",
        description="List in order [longitude, latitude]"
    )

    # Accept ANY key–value pair for properties
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        title="Properties",
        description="Dynamic key-value metadata"
    )

    style: Optional[FeatureStyle] = Field(
        None,
        title="Style Options",
        description="Styling for map rendering"
    )

class TableFormat(BaseModel):
    table_name: str = Field(..., title="Table name")
    column_names: list[str] = Field(..., title="Columns")
    data: list[list[str | int | bool]] = Field(..., title="Rows and Columns")

class TableLayout(BaseModel):
    type: str = Field(..., title="Table Layout")
    data: TableFormat = Field(..., title="Table format")

class FormLayout(BaseModel):
    type: str =  Field(default="form", title="Form Layout")
    data: Dict[str, Any] = Field(..., title="FormSchema")
    actions: Dict[str, Any] = Field(..., title="Actions")

class FormSchema(BaseModel):
    title: str = Field(..., title="Form name")
    description: Optional[str] = Field(None, title="description")
    schema_def: Dict[str, Any] = Field(..., title="Form Schema") # JSON Schema compatible

    