#################################################################
# Copyright (c) 2018 POET Industries
#
# This code is distributed under the MIT License. For a complete
# list of terms see accompanying LICENSE file or the copy at
# https://opensource.org/licenses/MIT
#################################################################

bl_info = {
    "name": "Action Transfer",
    "author": "POET Industries",
    "version": (0, 1, 0),
    "blender": (2, 78, 0),
    "category": "Animation"
}

import bpy, json, collections, os

################################################################
# TODO documentation goes here
################################################################
class ActionMapData(bpy.types.PropertyGroup):
    source = bpy.props.StringProperty(name="Source Bone")
    target = bpy.props.StringProperty(name="Target Bone")

class ActionTransferData(bpy.types.PropertyGroup):
    mapping = bpy.props.CollectionProperty(type=ActionMapData, name="Mapping")
    action = bpy.props.StringProperty(name="Action")
    prefix_src = bpy.props.StringProperty(name="Source Prefix")
    prefix_tgt = bpy.props.StringProperty(name="Target Prefix")


################################################################
# Transfer an action from one skeletonn to another. This is
# done by renaming the curves in the action from old bone names
# to their counterparts in the active skeleton.
#################################################################
class TransferToActive(bpy.types.Operator):
    """Transfer an action from one skeleton to another"""
    bl_idname = "anim.at_transfer_to_active"
    bl_label = "Action Transfer: Transfer to Active"
    bl_options = {'REGISTER', 'UNDO'}

    skel = None
    action = None

    @classmethod
    def poll(cls, context):
        is_mode = context.active_object.mode in ['OBJECT', 'POSE']
        has_action = context.scene.at_data.action is not ""
        is_complete = False
        for mapping in context.scene.at_data.mapping:
            if mapping.target != "":
                is_complete = True
                break
        return is_mode and has_action and is_complete

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None and obj.select and validate_mapping(obj, False):
            self.skel = obj
            if self.skel.animation_data is None:
                self.skel.animation_data_create()

        self.action = bpy.data.actions[context.scene.at_data.action]
        if self.action is None:
            self.report({'ERROR'}, "No action selected.")
            return {'CANCELLED'}
        if not validate_action():
            self.report({'ERROR'}, "Action doesn't match source skeleton's bones.")
            return {'CANCELLED'}

        name = self.action.name + ".transfer"
        if name in bpy.data.actions:
            bpy.data.actions[name].name += ".BCKP"
        self.action = self.action.copy()
        self.action.name = name

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        curves = self.action.fcurves
        mapping = context.scene.at_data.mapping
        src_bone = ""
        tgt_bone = ""
        is_used = False
        for c in curves:
            segments = c.data_path.split("\"")
            if len(segments) != 3:
                return {'CANCELLED'}
            if src_bone != segments[1]:
                src_bone = segments[1];
                for m in mapping:
                    if m.source == src_bone:
                        is_used = m.target != ""
                        tgt_bone = m.target
                        break
            if not is_used:
                curves.remove(c)
                continue
            segments[1] = tgt_bone
            c.data_path = "\"".join(segments)
        if self.skel is not None:
            self.skel.animation_data.action = self.action

        return {'FINISHED'}


################################################################
# The mapping between bone names is done in one of two ways:
# 1. The skeletons' hierarchies match and the correct mapping
#    can be inferred from that. This also works if the source
#    skeleton's hierarchy is a subset of the active skeleton.
# 2. The mapping is provided by a mapping configuration. This
#    configuration can be saved to and loaded from JSON files
#    in order to build a library of different skeleton mappings.
################################################################
class CollectBones(bpy.types.Operator):
    """Collect bone hierarchy from selected objects to create a new mapping."""
    bl_idname = "anim.at_collect_bones"
    bl_label = "Action Transfer: Collect Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        is_num = 1 <= len(context.selected_objects) <= 2
        is_mode = context.active_object.mode == 'OBJECT'
        is_type = True
        for obj in context.selected_objects:
            if obj.type != 'ARMATURE':
                is_type = False
        return is_num and is_mode and is_type

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.scene.at_data.mapping.clear()
        if len(context.selected_objects) == 2:
            self.collect_from_pair(context)
        else:
            self.collect_from_single(context, context.active_object)
        context.area.tag_redraw()
        return {'FINISHED'}

    def collect_from_single(self, context, skel):
        print("1 skeleton selected, collecting bones...")
        for bone in skel.data.bones:
            entry = context.scene.at_data.mapping.add()
            entry.source = bone.name

    def collect_from_pair(self, context):
        print("2 skeletons selected, tying to infer hierarchy...")
        source = None
        target = None
        for obj in context.selected_objects:
            if obj == context.active_object:
                target = obj
            else:
                source = obj

        # find source and target extremities, i.e. hands, feet & head
        data = context.scene.at_data
        src_ext = {}
        tgt_ext = {}
        for bone in source.data.bones:
            entry = data.mapping.add()
            entry.source = bone.name
            self.find_extremities(bone, data.prefix_src, src_ext)
        for bone in target.data.bones:
            self.find_extremities(bone, data.prefix_tgt, tgt_ext)

        # use extremities to guess parts of the bone hierarchies
        for idx in src_ext:
            if idx in tgt_ext:
                src_bone = src_ext[idx]
                tgt_bone = tgt_ext[idx]
                while src_bone is not None and tgt_bone is not None:
                    entry = mapping_entry_by_source(src_bone.name)
                    if entry is None or entry.target != "":
                        break
                    entry.target = tgt_bone.name
                    src_bone = src_bone.parent
                    tgt_bone = tgt_bone.parent

    def find_extremities(self, bone, prefix, out_struct):
        name = bone.name
        if name.startswith(prefix):
            name = name[len(prefix):]
        name = name.lower()

        if "head" in name and 'head' not in out_struct:
            out_struct['head'] = bone
        elif "hand" in name:
            if "r" in name and 'hand_r' not in out_struct:
                if 'hand_l' not in out_struct or out_struct['hand_l'] not in bone.parent_recursive:
                    out_struct['hand_r'] = bone
            elif "l" in name and 'hand_l' not in out_struct:
                if 'hand_r' not in out_struct or out_struct['hand_r'] not in bone.parent_recursive:
                    out_struct['hand_l'] = bone
        elif "foot" in name:
            if "r" in name and 'foot_r' not in out_struct:
                if 'foot_l' not in out_struct or out_struct['foot_l'] not in bone.parent_recursive:
                    out_struct['foot_r'] = bone
            elif "l" in name and 'foot_l' not in out_struct:
                if 'foot_r' not in out_struct or out_struct['foot_r'] not in bone.parent_recursive:
                    out_struct['foot_l'] = bone


################################################################
# Resets the data to its original state, deleting the mapping
# and all prefixes. Useful for starting over.
################################################################
class ClearData(bpy.types.Operator):
    """Clear out and reset all collected mapping data."""
    bl_idname = "anim.at_clear_data"
    bl_label = "Action Transfer: Clear Data"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        data = context.scene.at_data
        has_mapping = len(data.mapping) > 0
        has_prefix = data.prefix_src != "" or data.prefix_tgt != ""
        has_action = data.action != ""
        return has_mapping or has_prefix or has_action

    def execute(self, context):
        data = context.scene.at_data
        data.mapping.clear()
        data.prefix_src = ""
        data.prefix_tgt = ""
        data.action = ""
        context.area.tag_redraw()
        return {'FINISHED'}

################################################################
# Verifies that the data as it's currently set up is correct.
# Correctness is determined by two factors:
# 1. Mapping has to match the skeleton it's related to. There
#    has to be at least one bone in the mapping and all bones
#    in the mapping have to exist in the skeleton. Conversely,
#    not all bones in the skeleton have to be mapped.
# 2. All bone curves that exist in the selected action have
#    to correspond to bones in the source mapping. Again,
#    not all mapped bones need to be present in the animation.
################################################################
class ValidateMapping(bpy.types.Operator):
    """Checks if the current mapping is correct and matches the animation to be transferred."""
    bl_idname = "anim.at_validate_mapping"
    bl_label = "Action Transfer: Validate Mapping"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    skel_src = None
    skel_tgt = None

    @classmethod
    def poll(cls, context):
        objs = context.selected_objects
        if len(objs) != 2:
            return False
        for o in objs:
            if o.type != 'ARMATURE':
                return False
        if len(context.scene.at_data.mapping) == 0:
            return False
        return True

    def invoke(self, context, event):
        for obj in context.selected_objects:
            if obj.type != 'ARMATURE':
                return {'CANCELLED'}
            if obj == context.active_object:
                self.skel_tgt = obj
            else:
                self.skel_src = obj
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.scene.at_data.action == "":
            self.report({'WARNING'}, "No action selected.")
            return {'CANCELLED'}
        if not validate_action():
            self.report({'WARNING'}, "Action doesn't match the source mapping.")
            return {'CANCELLED'}
        if not validate_mapping(self.skel_src, True):
            self.report({'WARNING'}, "Source mapping doesn't match selected source skeleton.")
            return {'CANCELLED'}
        if not validate_mapping(self.skel_tgt, False):
            self.report({'WARNING'}, "Target mapping doesn't match selected target skeleton.")
            return {'CANCELLED'}
        self.report({'INFO'}, "Validation succeeded.")
        return {'FINISHED'}


################################################################
# Saves the current bone mapping between source and target
# skeletons to a JSON-formatted file. This functionality is
# intended to provide a method of working with and managing
# different, reusable mapping schemes between different rigs.
################################################################
class SaveToFile(bpy.types.Operator):
    """Save the current mapping to JSON-formatted file."""
    bl_idname = "anim.at_save_mapping"
    bl_label = "Save Mapping"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    filepath = bpy.props.StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        data = context.scene.at_data
        if len(data.mapping) == 0:
            return False
        has_source = False
        has_target = False
        for m in data.mapping:
            if m.source != "":
                has_source = True
            if m.target != "":
                has_target = True
            if has_source and has_target:
                return True
        return False

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        data = context.scene.at_data
        bones = collections.OrderedDict()
        for m in data.mapping:
            bones[m.source] = m.target
        mapping = collections.OrderedDict()
        mapping["prefix_src"] = data.prefix_src
        mapping["prefix_tgt"] = data.prefix_tgt
        mapping["bones"] = bones

        if not self.filepath.endswith(".json"):
            self.filepath += ".json"
        file = open(self.filepath, 'w')
        file.write(json.dumps(mapping, indent=4))
        file.close()
        return {'FINISHED'}


################################################################
# Loads a saved bone mapping between source and target
# skeletons from a JSON-formatted file. This functionality is
# intended to provide a method of working with and managing
# different, reusable mapping schemes between different rigs.
################################################################
class LoadFromFile(bpy.types.Operator):
    """Load mapping from JSON-formatted file."""
    bl_idname = "anim.at_load_mapping"
    bl_label = "Load Mapping"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    filepath = bpy.props.StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            file = open(self.filepath)
            mapping = json.load(file, object_pairs_hook=collections.OrderedDict)
        except FileNotFoundError:
            self.report({'WARNING'}, "The mapping file doesn't exist.")
        except json.JSONDecodeError:
            self.report({'WARNING'}, "The mapping file contains invalid JSON.")
            file.close()
        else:
            file.close()
            data = context.scene.at_data
            data.mapping.clear()
            data.prefix_src = mapping["prefix_src"]
            data.prefix_tgt = mapping["prefix_tgt"]
            for s, t in mapping["bones"].items():
                m = data.mapping.add()
                m.source = s
                m.target = t
            return {'FINISHED'}
        return {'CANCELLED'}


################################################################
# TODO documentation goes here
################################################################
class MainPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_action_transfer_main"
    bl_label = "Action Transfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Animation"
    bl_context = "objectmode"

    @classmethod
    def poll(cls, context):
        skel = context.active_object
        return skel is not None and skel.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        source = context.active_object

        col = layout.column(align=True)
        col.label("Action:")
        col.prop_search(context.scene.at_data, "action", bpy.data, "actions", text="")
        col.operator("anim.at_transfer_to_active", text="Transfer Action")

        col = layout.column(align=True)
        col.label("Mapping:")
        col.operator("anim.at_collect_bones", text="Collect Bones")
        col = layout.column(align=True)
        #col.operator("anim.at_xxx", text="Guess Hierarchy")
        col.operator("anim.at_validate_mapping", text="Validate Mapping")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("anim.at_save_mapping", text="Save to File", icon='SAVE_COPY')
        row.operator("anim.at_load_mapping", text="Load from File", icon='FILE_FOLDER')
        col.operator("anim.at_clear_data", text="Clear All", icon='CANCEL')

        col = layout.column(align=True)
        row = col.row(align=True)
        row.label("Source:")
        row.label("Target:")
        row = col.row(align=True)
        row.prop(context.scene.at_data, "prefix_src", text="", icon='FILTER')
        row.prop(context.scene.at_data, "prefix_tgt", text="", icon='FILTER')
        col = layout.column(align=True)
        for mapping in context.scene.at_data.mapping:
            row = col.row(align=True)
            row.prop_search(mapping, "source", source.pose, "bones", text="")
            row.prop_search(mapping, "target", source.pose, "bones", text="")


################################################################
# Static helper function. TODO documentation
################################################################
def mapping_entry_by_source(bone_name):
    for entry in bpy.context.scene.at_data.mapping:
        if entry.source == bone_name:
            return entry
    return None

################################################################
# Static helper function. TODO documentation
################################################################
def validate_mapping(skeleton, compare_to_source):
    if skeleton.type != 'ARMATURE':
        return False
    data = bpy.context.scene.at_data.mapping
    mapping = [m.source for m in data] if compare_to_source else [m.target for m in data]
    bones = skeleton.data.bones
    count = 0
    for m in mapping:
        if m != "":
            count += 1
            if m not in bones:
                return False
    return count != 0


################################################################
# Static helper function. TODO documentation
################################################################
def validate_action():
    key = bpy.context.scene.at_data.action
    if key not in bpy.data.actions:
        return False
    action = bpy.data.actions[key]
    if action is None:
        return False
    mapping = bpy.context.scene.at_data.mapping
    for c in action.fcurves:
        path = c.data_path.split("\"")
        if len(path) != 3:
            return False
        if path[1] not in [m.source for m in bpy.context.scene.at_data.mapping]:
            return False
    return True


#################### boring init stuff ############################

def register():
    bpy.utils.register_class(ActionMapData)
    bpy.utils.register_class(ActionTransferData)
    bpy.utils.register_class(TransferToActive)
    bpy.utils.register_class(CollectBones)
    bpy.utils.register_class(ClearData)
    bpy.utils.register_class(ValidateMapping)
    bpy.utils.register_class(SaveToFile)
    bpy.utils.register_class(LoadFromFile)
    bpy.utils.register_class(MainPanel)

    bpy.types.Scene.at_data = bpy.props.PointerProperty(type=ActionTransferData)


def unregister():
    del bpy.types.Scene.at_data

    bpy.utils.unregister_class(ActionMapData)
    bpy.utils.unregister_class(ActionTransferData)
    bpy.utils.unregister_class(TransferToActive)
    bpy.utils.unregister_class(CollectBones)
    bpy.utils.unregister_class(ClearData)
    bpy.utils.unregister_class(ValidateMapping)
    bpy.utils.unregister_class(SaveToFile)
    bpy.utils.unregister_class(LoadFromFile)
    bpy.utils.unregister_class(MainPanel)


if __name__ == "__main__":
    register()
