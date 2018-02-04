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

import bpy

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

    @classmethod
    def poll(cls, context):
        is_mode = context.active_object.mode in ['OBJECT', 'POSE']
        is_complete = context.scene.at_data.action is not ""
        for mapping in context.scene.at_data.mapping:
            if mapping.target is None or mapping.target is "":
                is_complete = False
        return is_mode and is_complete

    def invoke(self, context, event):
        for obj in context.selected_objects:
            if obj != context.active_object:
                print(obj.data.name)
                break
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


    def modal(self, context, event):
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
                    entry = get_transfer_mapping_by_source(src_bone.name)
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
        col.operator("anim.at_collect_bones", text="Guess Hierarchy")
        col.operator("anim.at_collect_bones", text="Verify Mapping")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("anim.at_collect_bones", text="Save to File", icon='SAVE_COPY')
        row.operator("anim.at_collect_bones", text="Load from File", icon='FILE_FOLDER')
        col.operator("anim.at_collect_bones", text="Clear All", icon='CANCEL')

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
# TODO documentation goes here
################################################################
def get_transfer_mapping_by_source(bone_name):
    for entry in bpy.context.scene.at_data.mapping:
        if entry.source == bone_name:
            return entry
    return None

#################### boring init stuff ############################

def register():
    bpy.utils.register_class(ActionMapData)
    bpy.utils.register_class(ActionTransferData)
    bpy.utils.register_class(TransferToActive)
    bpy.utils.register_class(CollectBones)
    bpy.utils.register_class(MainPanel)

    bpy.types.Scene.at_data = bpy.props.PointerProperty(type=ActionTransferData)


def unregister():
    del bpy.types.Scene.at_data

    bpy.utils.unregister_class(ActionMapData)
    bpy.utils.unregister_class(ActionTransferData)
    bpy.utils.unregister_class(TransferToActive)
    bpy.utils.unregister_class(CollectBones)
    bpy.utils.unregister_class(MainPanel)


if __name__ == "__main__":
    register()
