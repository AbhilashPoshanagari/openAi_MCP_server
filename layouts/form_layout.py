

from typing import Any, Dict, List

from layoutSchema.form_shema import FormWidget, WidgetType


def generate_form_schema(widgets: List[FormWidget]) -> Dict[str, Any]:
    """Generate JSON Schema from widgets"""
    properties = {}
    required_fields = []
    
    for widget in widgets:
        field_schema = {
            "title": widget.label,
            "type": get_field_type(widget.type),
            "widgetType": widget.type.value,
            "position": widget.position
        }
        
        # Add constraints
        if widget.minLength is not None:
            field_schema["minLength"] = int(widget.minLength)
        if widget.maxLength is not None:
            field_schema["maxLength"] = int(widget.maxLength)
        if widget.placeholder:
            field_schema["description"] = widget.placeholder
        if widget.defaultValue:
            field_schema["default"] = widget.defaultValue
            
        # Add options for selection widgets
        if widget.options and widget.type in [WidgetType.DROPDOWN, WidgetType.SELECT, WidgetType.RADIO, WidgetType.STATUS]:
            field_schema["enum"] = [opt.value for opt in widget.options]
            field_schema["options"] = [{"label": opt.displayValue, "value": opt.value} for opt in widget.options]
            
        # Required fields
        if widget.isRequired:
            required_fields.append(widget.id)
            
        properties[widget.id] = field_schema
    
    return {
        "type": "object",
        "properties": properties,
        "required": required_fields,
        "additionalProperties": False
    }

def get_field_type(widget_type: WidgetType) -> str:
    """Map widget type to JSON Schema type"""
    mapping = {
        WidgetType.TEXTBOX: "string",
        WidgetType.TEXTAREA: "string",
        WidgetType.EMAIL: "string",
        WidgetType.NUMBER: "number",
        WidgetType.DATE: "string",  # date format handled by UI
        WidgetType.DROPDOWN: "string",
        WidgetType.SELECT: "string",
        WidgetType.RADIO: "string",
        WidgetType.CHECKBOX: "boolean",
        WidgetType.STATUS: "string"
    }
    return mapping.get(widget_type, "string")