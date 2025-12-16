from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator, validator
from enum import Enum


# Enums for consistent values
class GeometryType(str, Enum):
    POINT = "Point"
    LINE_STRING = "LineString"
    POLYGON = "Polygon"
    MULTI_POINT = "MultiPoint"
    MULTI_LINE_STRING = "MultiLineString"
    MULTI_POLYGON = "MultiPolygon"


class FeatureType(str, Enum):
    FEATURE = "Feature"
    FEATURE_COLLECTION = "FeatureCollection"


class StyleType(str, Enum):
    FILL = "fill"
    LINE = "line"
    CIRCLE = "circle"
    SYMBOL = "symbol"
    RASTER = "raster"


# Pydantic models for geometry
class GeometryBase(BaseModel):
    type: GeometryType = Field(..., title="Geometry Type")
    coordinates: Any = Field(..., title="Coordinates")


class PointGeometry(GeometryBase):
    type: Literal[GeometryType.POINT] = GeometryType.POINT
    coordinates: List[float] = Field(
        ...,
        title="Point Coordinates",
        description="List in order [longitude, latitude]",
        min_items=2,
        max_items=3
    )

    @field_validator('coordinates')
    def validate_coordinates(cls, v):
        if len(v) not in [2, 3]:
            raise ValueError('Coordinates must have 2 or 3 elements')
        lon, lat = v[0], v[1]
        if not (-180 <= lon <= 180):
            raise ValueError('Longitude must be between -180 and 180')
        if not (-90 <= lat <= 90):
            raise ValueError('Latitude must be between -90 and 90')
        return v


class LineStringGeometry(GeometryBase):
    type: Literal[GeometryType.LINE_STRING] = GeometryType.LINE_STRING
    coordinates: List[List[float]] = Field(
        ...,
        title="LineString Coordinates",
        description="List of coordinate pairs [[lon, lat], ...]",
        min_items=2
    )


class PolygonGeometry(GeometryBase):
    type: Literal[GeometryType.POLYGON] = GeometryType.POLYGON
    coordinates: List[List[List[float]]] = Field(
        ...,
        title="Polygon Coordinates",
        description="List of linear rings, where each ring is a list of coordinates"
    )


# Union type for all geometry types
Geometry = Union[
    PointGeometry,
    LineStringGeometry,
    PolygonGeometry,
    GeometryBase  # Fallback for other types
]


# Pydantic model for style
class FeatureStyle(BaseModel):
    # type: StyleType = Field(..., title="Style Type")
    color: Optional[str] = Field(None, title="Color", pattern="^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    opacity: Optional[float] = Field(None, title="Opacity", ge=0, le=1)
    radius: Optional[float] = Field(None, title="Radius", ge=0)
    width: Optional[float] = Field(None, title="Width", ge=0)
    icon: Optional[str] = Field(None, title="Icon URL")
    icon_size: Optional[float] = Field(None, title="Icon Size", ge=0)
    fill: Optional[bool] = Field(None, title="Fill")
    stroke: Optional[bool] = Field(None, title="Stroke")

    class Config:
        extra = "allow"  # Allow additional style properties


# Pydantic model for properties
class FeatureProperties(BaseModel):
    name: str = Field(..., title="Name")
    type: str = Field(..., title="Type")  # Changed from category to type
    address: Optional[str] = Field(None, title="Address")
    
    class Config:
        extra = "allow"  # Allow additional properties


# Main Feature model
class MapFeature(BaseModel):
    type: Literal[FeatureType.FEATURE] = FeatureType.FEATURE
    geometry: Geometry = Field(..., title="Geometry")
    properties: Union[FeatureProperties, Dict[str, Any]] = Field(
        ...,
        title="Properties",
        description="Feature properties"
    )
    id: Optional[str] = Field(None, title="Feature ID")
    style: Optional[FeatureStyle] = Field(
        None,
        title="Style Options",
        description="Styling for map rendering"
    )
    
    @field_validator('properties', mode='before')
    def validate_properties(cls, v):
        if isinstance(v, dict) and 'name' in v and 'type' in v:
            # Convert dict to FeatureProperties if it has required fields
            return FeatureProperties(**v)
        return v
    
    def get_coordinates(self) -> List[float]:
        """Get coordinates as [longitude, latitude] for point features"""
        if isinstance(self.geometry, PointGeometry):
            return self.geometry.coordinates[:2]  # Return only lat, lon (ignore altitude if present)
        raise ValueError("Coordinates only available for Point geometries")
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a property value by key"""
        if isinstance(self.properties, dict):
            return self.properties.get(key, default)
        return getattr(self.properties, key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert feature to dictionary format"""
        return self.model_dump(exclude_none=True)


# Feature Collection model
class FeatureCollection(BaseModel):
    type: Literal[FeatureType.FEATURE_COLLECTION] = FeatureType.FEATURE_COLLECTION
    features: List[MapFeature] = Field(..., title="Features")
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        title="Collection Metadata"
    )


# MapFeatures class
class MapFeatures:
    def __init__(self):
        self.features: List[MapFeature] = []
        self.collection: Optional[FeatureCollection] = None
    
    def add_feature(self, feature_data: Union[Dict[str, Any], MapFeature]) -> MapFeature:
        """Add and validate a single feature"""

        if isinstance(feature_data, MapFeature):
            # Already a MapFeature object
            self.features.append(feature_data)
            return feature_data
        # Ensure geometry is properly structured
        if 'geometry' in feature_data and isinstance(feature_data['geometry'], dict):
            geom_type = feature_data['geometry'].get('type')
            coords = feature_data['geometry'].get('coordinates', [])
            
            if geom_type == GeometryType.POINT:
                feature_data['geometry'] = PointGeometry(
                    type=GeometryType.POINT,
                    coordinates=coords
                )
            elif geom_type == GeometryType.LINE_STRING:
                feature_data['geometry'] = LineStringGeometry(
                    type=GeometryType.LINE_STRING,
                    coordinates=coords
                )
            elif geom_type == GeometryType.POLYGON:
                feature_data['geometry'] = PolygonGeometry(
                    type=GeometryType.POLYGON,
                    coordinates=coords
                )
            else:
                feature_data['geometry'] = GeometryBase(
                    type=geom_type,
                    coordinates=coords
                )
        
        # Validate and create feature
        feature = MapFeature(**feature_data)
        self.features.append(feature)
        return feature
    
    def add_features_from_list(self, features_list: List[Dict[str, Any]]) -> List[MapFeature]:
        """Add multiple features from a list"""
        added_features = []
        for feature_data in features_list:
            feature = self.add_feature(feature_data)
            added_features.append(feature)
        return added_features
    
    def create_collection(self, metadata: Optional[Dict[str, Any]] = None) -> FeatureCollection:
        """Create a feature collection from all added features"""
        self.collection = FeatureCollection(
            type=FeatureType.FEATURE_COLLECTION,
            features=self.features,
            metadata=metadata or {}
        )
        return self.collection
    
    def get_feature_by_id(self, feature_id: str) -> Optional[MapFeature]:
        """Get a feature by its ID"""
        for feature in self.features:
            if feature.id == feature_id:
                return feature
        return None
    
    def get_features_by_type(self, feature_type: str) -> List[MapFeature]:
        """Get all features with a specific type"""
        return [
            feature for feature in self.features
            if feature.get_property('type') == feature_type
        ]
    
    def to_geojson(self) -> Dict[str, Any]:
        """Convert to GeoJSON format"""
        if not self.collection:
            self.create_collection()
        
        return self.collection.model_dump(exclude_none=True)
    
    def validate_all_features(self) -> bool:
        """Validate all features in the collection"""
        try:
            if not self.collection:
                self.create_collection()
            
            # Pydantic will raise ValidationError if invalid
            self.collection = FeatureCollection(**self.collection.model_dump())
            return True
        except Exception as e:
            print(f"Validation error: {e}")
            return False
    
    def get_all_features(self) -> List[MapFeature]:
        """Get all features as a list"""
        return self.features


# Example usage with your data
class MapLayout(MapFeatures):
    def __init__(self):
        super().__init__()
        self._load_default_features()
    
    def _load_default_features(self):
        """Load the default features provided in the example"""
        features_details = [
              {
                "id": '2',
                "name": 'Line Feature',
                "type": 'Feature',
                "geometry": {
                    "type": 'LineString',
                    "coordinates": [[78.37385, 17.43352], [78.38012, 17.43190]]
                    },
                "properties": { "length": '2km' },
                "style": { "color": '#3388ff', "weight": 5 }
            },
            {
                "type": "Feature",
                "id": "rest_1",
                "properties": {
                    "name": "Third Wave Coffee",
                    "type": "Cafe",
                    "address": "Knowledge City, Raidurg"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.37385, 17.43352]
                }
            },
            {
                "type": "Feature",
                "id": "rest_2",
                "properties": {
                    "name": "Airplane Food Court Restaurant",
                    "type": "Multi-Cuisine",
                    "address": "Near Durgam Cheruvu, Raidurg"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38012, 17.43190]
                }
            },
            {
                "type": "Feature",
                "id": "rest_3",
                "properties": {
                    "name": "Tovo",
                    "type": "Fast Food",
                    "address": "Gachibowli–Raidurg Road"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.37320, 17.43710]
                }
            },
            {
                "type": "Feature",
                "id": "rest_4",
                "properties": {
                    "name": "Cafe Coffee Day (Raidurg Metro)",
                    "type": "Cafe",
                    "address": "Raidurg Metro Station"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38195, 17.43482]
                }
            },
            {
                "type": "Feature",
                "id": "rest_5",
                "properties": {
                    "name": "Eat India Company",
                    "type": "Indian",
                    "address": "Inorbit Mall Road, Raidurg"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38500, 17.43310]
                }
            },
            {
                "type": "Feature",
                "id": "rest_6",
                "properties": {
                    "name": "Absolute Barbecues",
                    "type": "BBQ",
                    "address": "Hitech City Main Road"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38275, 17.44250]
                }
            },
            {
                "type": "Feature",
                "id": "rest_7",
                "properties": {
                    "name": "Chutneys",
                    "type": "South Indian",
                    "address": "Hitech City"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38490, 17.44600]
                }
            },
            {
                "type": "Feature",
                "id": "rest_8",
                "properties": {
                    "name": "Cafe De Loco",
                    "type": "Pet Friendly Cafe",
                    "address": "Jubilee Hills Road No. 45"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.39950, 17.43680]
                }
            },
            {
                "type": "Feature",
                "id": "rest_9",
                "properties": {
                    "name": "Leon's Burgers & Wings",
                    "type": "Fast Food",
                    "address": "Hitech City"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.38120, 17.44700]
                }
            },
            {
                "type": "Feature",
                "id": "rest_10",
                "properties": {
                    "name": "Minerva Coffee Shop",
                    "type": "South Indian",
                    "address": "Madhapur"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.39380, 17.44120]
                }
            }
        ]
        
        self.add_features_from_list(features_details)
        self.create_collection(metadata={
            "name": "Hyderabad Restaurants",
            "description": "Restaurants in Hyderabad area",
            "created": "2024-01-01"
        })
    
    def featureDetails(self) -> List[Dict[str, Any]]:
        """Return feature details as a list of dictionaries"""
        details = []
        for i, feature in enumerate(self.features):
            feature_dict = {
                "id": feature.id or f"feature_{i}",
                "name": feature.get_property('name'),
                "type": feature.geometry.type.value,
                "coordinates": feature.get_coordinates(),
                "properties": feature.properties.model_dump() if isinstance(feature.properties, BaseModel) else feature.properties
            }
            if feature.style:
                feature_dict["style"] = feature.style.model_dump()
            details.append(feature_dict)
        return details

