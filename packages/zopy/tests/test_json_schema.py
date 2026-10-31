import pytest

from zopy import z


def strip(schema):
    schema = dict(schema)
    schema.pop("$schema", None)
    return schema


def test_primitives():
    assert strip(z.toJSONSchema(z.string())) == {"type": "string"}
    assert strip(z.toJSONSchema(z.string().min(2).max(5).regex(r"^a"))) == {
        "type": "string",
        "minLength": 2,
        "maxLength": 5,
        "pattern": "^a",
    }
    assert strip(z.toJSONSchema(z.email())) == {"type": "string", "format": "email"}
    assert strip(z.toJSONSchema(z.number().gt(0).lte(10))) == {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 10,
    }
    assert strip(z.toJSONSchema(z.int())) == {"type": "integer"}
    assert strip(z.toJSONSchema(z.boolean())) == {"type": "boolean"}
    assert strip(z.toJSONSchema(z.null())) == {"type": "null"}
    assert strip(z.toJSONSchema(z.literal("a"))) == {"type": "string", "const": "a"}
    assert strip(z.toJSONSchema(z.literal("a"), {"target": "openapi-3.0"})) == {
        "type": "string",
        "enum": ["a"],
    }
    assert strip(z.toJSONSchema(z.literal([1, 2]))) == {"type": "number", "enum": [1, 2]}
    assert strip(z.toJSONSchema(z.enum(("a", "b")))) == {"type": "string", "enum": ["a", "b"]}
    assert strip(z.toJSONSchema(z.int().positive(), {"target": "openapi-3.0"})) == {
        "type": "integer",
        "minimum": 0,
        "exclusiveMinimum": True,
    }
    assert strip(z.toJSONSchema(z.any())) == {}
    assert strip(z.toJSONSchema(z.never())) == {"not": {}}


def test_object_and_composites():
    class User(z.Object):
        name = z.string()
        age = z.number().optional()
        role = z.string().default("user")

    js = strip(z.toJSONSchema(User))
    assert js == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "number"},
            "role": {"type": "string", "default": "user"},
        },
        "required": ["name", "role"],
        "additionalProperties": False,
    }
    inp = strip(z.toJSONSchema(User, {"io": "input"}))
    assert inp["required"] == ["name"]
    assert "additionalProperties" not in inp

    class Loose(z.LooseObject):
        pass

    assert strip(z.toJSONSchema(Loose))["additionalProperties"] == {}
    assert strip(z.toJSONSchema(z.array(z.string()).min(1))) == {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
    }
    assert strip(z.toJSONSchema(z.tuple((z.string(), z.number())))) == {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "number"}],
        "minItems": 2,
        "maxItems": 2,
    }
    assert strip(z.toJSONSchema(z.union([z.string(), z.number()]))) == {
        "anyOf": [{"type": "string"}, {"type": "number"}]
    }
    assert strip(z.toJSONSchema(z.string().nullable())) == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert strip(z.toJSONSchema(z.record(z.string(), z.number()))) == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }


def test_meta_and_unrepresentable():
    s = z.string().meta({"title": "Name", "description": "A name", "examples": ["Ada"]})
    assert strip(z.toJSONSchema(s)) == {
        "type": "string",
        "title": "Name",
        "description": "A name",
        "examples": ["Ada"],
    }
    assert strip(z.toJSONSchema(z.string().meta({"description": "desc"}))) == {
        "type": "string",
        "description": "desc",
    }
    with pytest.raises(ValueError, match="Date cannot be represented"):
        z.toJSONSchema(z.date())
    assert strip(z.toJSONSchema(z.date(), {"unrepresentable": "any"})) == {}
    assert strip(z.toJSONSchema(z.string().transform(lambda s: len(s)), {"io": "input"})) == {
        "type": "string"
    }
    with pytest.raises(ValueError, match="Transforms cannot be represented"):
        z.toJSONSchema(z.string().transform(lambda s: len(s)))


def test_recursive():
    class Category(z.Object):
        name = z.string()
        children = z.lazy(lambda: z.array(Category))

    js = z.toJSONSchema(Category)
    assert js["properties"]["children"]["items"] == {"$ref": "#"}

    # non-root recursion is hoisted into $defs
    class Leaf(z.Object):
        name = z.string()
        kids = z.lazy(lambda: z.array(Leaf))

    class Root(z.Object):
        leaf = Leaf

    js = z.toJSONSchema(Root)
    assert js["properties"]["leaf"]["$ref"].startswith("#/$defs/")
    name = js["properties"]["leaf"]["$ref"].split("/")[-1]
    assert js["$defs"][name]["properties"]["kids"]["items"]["$ref"] == f"#/$defs/{name}"


def test_draft7_and_openapi():
    js = z.toJSONSchema(z.tuple((z.string(),)), {"target": "draft-7"})
    assert js["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert js["items"] == [{"type": "string"}]
    assert strip(z.toJSONSchema(z.string().nullable(), {"target": "openapi-3.0"})) == {
        "type": "string",
        "nullable": True,
    }


def test_schemas_with_id_are_extracted_into_defs():
    # Zod: "Any schema with an id property will be extracted as a $def" (id itself is dropped).
    class UserFields(z.Object):
        name = z.string()

    User = UserFields.meta({"id": "User", "title": "User"})

    class Post(z.Object):
        author = User
        reviewers = z.array(User)

    class Holder(z.Object):
        u = User

    js = z.toJSONSchema(Post)
    assert js["properties"]["author"] == {"$ref": "#/$defs/User"}
    assert js["properties"]["reviewers"]["items"] == {"$ref": "#/$defs/User"}
    assert js["$defs"]["User"]["title"] == "User"
    assert "id" not in js["$defs"]["User"]
    assert "$id" not in js["$defs"]["User"]
    assert z.toJSONSchema(Holder, {"target": "draft-7"})["properties"]["u"] == {"$ref": "#/definitions/User"}
    root = z.toJSONSchema(User)
    assert root["$ref"] == "#/$defs/User"
    assert set(root["$defs"]) == {"User"}


def test_id_schema_reused_for_two_fields_refs_both():
    class UserFields(z.Object):
        name = z.string()

    User = UserFields.meta({"id": "User"})

    class Post(z.Object):
        author = User
        editor = User

    js = z.toJSONSchema(Post)
    assert js["properties"]["author"] == {"$ref": "#/$defs/User"}
    assert js["properties"]["editor"] == {"$ref": "#/$defs/User"}

    Name = z.string().meta({"id": "Name"})

    class Pair(z.Object):
        first = Name
        second = Name

    props = z.toJSONSchema(Pair)["properties"]
    assert props["first"] == props["second"] == {"$ref": "#/$defs/Name"}


def test_class_schema_with_id_and_recursion():
    class Node(z.Object):
        value = z.int()
        kids = z.lazy(lambda: z.array(NodeWithId)).optional()

    NodeWithId = Node.meta({"id": "Node"})
    js = z.toJSONSchema(NodeWithId)
    assert js["$ref"] == "#/$defs/Node"
    assert js["$defs"]["Node"]["properties"]["kids"]["items"] == {"$ref": "#/$defs/Node"}


def test_openapi_metadata_and_uri():
    from zopy.registries import openapiParamRegistry

    class TodoFields(z.Object):
        id = z.int().openapi({"example": 1})

    Todo = TodoFields.openapi("Todo", {"description": "A todo"})

    class Holder(z.Object):
        t = Todo

    js = z.toJSONSchema(Holder, {"uri": lambda name: f"#/components/schemas/{name}"})
    assert js["properties"]["t"] == {"$ref": "#/components/schemas/Todo"}
    assert js["$defs"]["Todo"]["description"] == "A todo"
    assert js["$defs"]["Todo"]["properties"]["id"]["example"] == 1
    param = z.string().openapi({"param": {"name": "id", "in": "path"}, "example": "1"})
    assert openapiParamRegistry.get(param) == {"name": "id", "in": "path"}
    assert "param" not in z.toJSONSchema(param)
    assert openapiParamRegistry.get(param.openapi({"description": "kept"})) == {"name": "id", "in": "path"}
