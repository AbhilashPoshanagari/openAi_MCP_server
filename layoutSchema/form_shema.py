from pydantic import BaseModel, Field, field_validator, create_model
from typing import Any, Dict, List, Optional, Union
from enum import Enum


# -------------------
# ENUMS
# -------------------
class WidgetType(str, Enum):
    TEXTBOX = "textBox"
    STATUS = "status"
    DROPDOWN = "dropdown"
    SELECT = "select",
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textArea"
    NUMBER = "number"
    DATE = "date"
    EMAIL = "email"


# -------------------
# OPTION MODEL
# -------------------
class Option(BaseModel):
    displayValue: str
    value: str
    dependFields: Optional[Any] = None


# -------------------
# FORM WIDGET
# -------------------
class FormWidget(BaseModel):
    _id: str
    id: str
    label: str
    isRequired: Union[bool, str] = False
    placeholder: str = ""
    defaultValue: str = ""
    minLength: Optional[Union[str, int]] = None
    maxLength: Optional[Union[str, int]] = None
    type: WidgetType
    isUnderHeading: str = ""
    isDependentField: bool = False
    disabled: Optional[Union[str, int]] = None
    displayName: str = ""
    typeChange: str = ""
    dynamicDropdownTable: str = ""
    columnName: str = ""
    formId: str
    position: int
    __v: int = 0

    options: Optional[List[Option]] = None
    isReassign: Optional[bool] = None

    # -------------------
    # VALIDATORS (pydantic v2)
    # -------------------
    @field_validator("isRequired", mode="before")
    @classmethod
    def validate_is_required(cls, v):
        if v == "":
            return False
        return bool(v)

    @field_validator("minLength", "maxLength", mode="before")
    @classmethod
    def validate_lengths(cls, v):
        if v == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return v


# -------------------
# FORM INFO / DATA
# -------------------
class FormInfo(BaseModel):
    id: str = Field(alias='_id')
    name: str
    createdBy: str
    description: str
    dependentFields: List[Any] = Field(default_factory=list)
    displayField: List[Any] = Field(default_factory=list)
    version: str

    class Config:
        extra = "ignore" 
        populate_by_name = True


class FormData(BaseModel):
    formWidgets: List[FormWidget]
    isCurrentVersion: bool
    formInfo: FormInfo
    referenceList: List[Any] = Field(default_factory=list)
    recordInformation: List[Any] = Field(default_factory=list)


class FormResponse(BaseModel):
    data: FormData
    status: int


# -------------------
# DYNAMIC FORM GENERATOR
# -------------------
class DynamicFormGenerator:
    @staticmethod
    def widget_to_field(widget: FormWidget) -> tuple:
        """Convert a FormWidget to a Pydantic v2 field definition"""

        field_type = Any
        field_kwargs = {
            "title": widget.label,
            "description": f"Position: {widget.position}",
        }

        # Default value
        if widget.defaultValue:
            field_kwargs["default"] = widget.defaultValue

        # Required flag – still works via schema metadata
        if widget.isRequired:
            field_kwargs["json_schema_extra"] = {"required": True}

        # -------------------
        # TYPE LOGIC
        # -------------------
        if widget.type == WidgetType.TEXTBOX:
            field_type = str
            if widget.minLength is not None:
                field_kwargs["min_length"] = int(widget.minLength)
            if widget.maxLength is not None:
                field_kwargs["max_length"] = int(widget.maxLength)

        elif widget.type == WidgetType.STATUS:
            if widget.options:
                enum_members = {
                    opt.value.upper().replace(" ", "_"): opt.value
                    for opt in widget.options
                }

                options_enum = Enum(f"{widget.id}Status", enum_members)

                field_type = options_enum
                field_kwargs["description"] = (
                    f"Available options: {[opt.displayValue for opt in widget.options]}"
                )
            else:
                field_type = str

        elif widget.type in [WidgetType.DROPDOWN, WidgetType.RADIO]:
            field_type = str
            if widget.options:
                field_kwargs["json_schema_extra"] = {
                    "options": [opt.displayValue for opt in widget.options],
                    "option_values": [opt.value for opt in widget.options],
                }

        elif widget.type == WidgetType.CHECKBOX:
            field_type = bool

        elif widget.type == WidgetType.NUMBER:
            field_type = Union[int, float]
            if widget.minLength is not None:
                field_kwargs["ge"] = int(widget.minLength)
            if widget.maxLength is not None:
                field_kwargs["le"] = int(widget.maxLength)

        elif widget.type == WidgetType.EMAIL:
            field_type = str
            field_kwargs["pattern"] = (
                r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            )

        # Add placeholder
        if widget.placeholder:
            field_kwargs["description"] += f" - {widget.placeholder}"

        return field_type, Field(**field_kwargs)

    # -------------------
    # CREATE MODEL IN PYDANTIC v2
    # -------------------
    @classmethod
    def create_dynamic_form_model(
        cls, form_widgets: List[FormWidget], model_name: str = "DynamicForm"
    ) -> BaseModel:

        field_definitions = {}

        for widget in sorted(form_widgets, key=lambda x: x.position):
            field_name = cls.sanitize_field_name(widget.label or widget.id)
            field_type, field_obj = cls.widget_to_field(widget)
            field_definitions[field_name] = (field_type, field_obj)

        return create_model(
            model_name,
            __base__=BaseModel,
            **field_definitions,
        )

    @staticmethod
    def sanitize_field_name(name: str) -> str:
        """Convert label into safe python variable name"""
        import re

        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if sanitized and not sanitized[0].isalpha() and sanitized[0] != "_":
            sanitized = "_" + sanitized
        return sanitized.lower()
