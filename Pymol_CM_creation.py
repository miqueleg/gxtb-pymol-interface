from pymol import cmd

def make_cluster_model(selection="CM_sel",
                       tmp_obj="tmp1",
                       cm_obj="CM",
                       cm_fix_sel="CM_FIX"):
    """
    What the script does:
    1) Create temporal object that is a copy of the given selection.
    2) On tmp_obj, remove:
       - N-terminal N (with no C neighbor) AND only the H attached to those N
       - C-terminal C (with no N neighbor) AND only:
           * O/OXT attached to those C
           * H attached to those C
           * H attached to those O/OXT
       All other hydrogens (e.g., CA-H, sidechain H) are preserved.
    3) Create CM as a copy of tmp_obj.
    4) In CM: select CA and show them as spheres. This will make new H added to the CA to be spheres also.
    5) Add hydrogens to CM with h_add.
    6) Renumber atom IDs in CM from 1..N (for XYZ export).
    7) Create the CM_FIX selection as all atoms in CM that are in sphere representation.
    8) Delete tmp_obj.
    9) Print the final IDs of atoms in CM_FIX. This is for using them in the constraints list in xtb and CREST input
    """

    # ------------------------------------------------------------------
    # 1) Create tmp1 from the selection (clean old tmp1/CM first)
    # ------------------------------------------------------------------
    cmd.delete(tmp_obj)
    cmd.delete(cm_obj)
    cmd.delete(cm_fix_sel)

    cmd.create(tmp_obj, selection)

    # Optional: focus on tmp1 only
    cmd.disable(f"not {tmp_obj}")

    # ------------------------------------------------------------------
    # 2) REMOVE SPECIFIC BACKBONE ATOMS + ONLY THEIR DIRECT H (in tmp1)
    # ------------------------------------------------------------------

    # --- N-terminal N: N atoms with no bonded C in this object ---
    ntermN_sel = f"{tmp_obj}_NtermN"
    cmd.select(ntermN_sel, f"{tmp_obj} and name N and not neighbor ({tmp_obj} and name C)")

    # H attached to these N-terminal N
    ntermN_H_sel = f"{tmp_obj}_H_on_NtermN"
    cmd.select(ntermN_H_sel, f"{tmp_obj} and elem H and neighbor {ntermN_sel}")

    # Remove H on N-terminal N, then the N's themselves
    cmd.remove(ntermN_H_sel)
    cmd.remove(ntermN_sel)

    cmd.delete(ntermN_H_sel)
    cmd.delete(ntermN_sel)

    # --- C-terminal C: C atoms with no bonded N in this object ---
    ctermC_sel = f"{tmp_obj}_CtermC"
    cmd.select(ctermC_sel, f"{tmp_obj} and name C and not neighbor ({tmp_obj} and name N)")

    # O/OXT attached to those C-terminal C
    O_on_C_sel = f"{tmp_obj}_O_on_CtermC"
    cmd.select(O_on_C_sel, f"{tmp_obj} and (name O or name OXT) and neighbor {ctermC_sel}")

    # H attached directly to those C-terminal C
    H_on_C_sel = f"{tmp_obj}_H_on_CtermC"
    cmd.select(H_on_C_sel, f"{tmp_obj} and elem H and neighbor {ctermC_sel}")

    # H attached to the O/OXT that are attached to those C
    H_on_O_sel = f"{tmp_obj}_H_on_Oterm"
    cmd.select(H_on_O_sel, f"{tmp_obj} and elem H and neighbor {O_on_C_sel}")

    # Remove hydrogens first (on C and O/OXT), then O/OXT, then the C's
    cmd.remove(H_on_O_sel)
    cmd.remove(H_on_C_sel)
    cmd.remove(O_on_C_sel)
    cmd.remove(ctermC_sel)

    # Clean up temporary selections
    for s in (O_on_C_sel, H_on_C_sel, H_on_O_sel, ctermC_sel):
        cmd.delete(s)

    # ------------------------------------------------------------------
    # 3) Create CM as a copy of tmp1
    # ------------------------------------------------------------------
    cmd.create(cm_obj, tmp_obj)

    # ------------------------------------------------------------------
    # 4) In CM: show CA as spheres
    # ------------------------------------------------------------------
    cmd.hide("spheres", "all")
    cmd.show("spheres", f"{cm_obj} and name CA")

    # ------------------------------------------------------------------
    # 5) Add hydrogens in CM
    # ------------------------------------------------------------------
    cmd.h_add(cm_obj)

    # ------------------------------------------------------------------
    # 6) Renumber atom IDs in CM to start at 1 and be consecutive
    # ------------------------------------------------------------------
    model_cm = cmd.get_model(cm_obj)
    new_id = 1
    for atom in model_cm.atom:
        cmd.alter(f"{cm_obj} and index {atom.index}", f"ID={new_id}")
        new_id += 1

    cmd.sort(cm_obj)

    # ------------------------------------------------------------------
    # 7) CM_FIX = all atoms in CM currently in sphere representation
    # ------------------------------------------------------------------
    cmd.select(cm_fix_sel, f"{cm_obj} and rep spheres")

    # ------------------------------------------------------------------
    # 8) Remove temporary object
    # ------------------------------------------------------------------
    cmd.delete(tmp_obj)

    # ------------------------------------------------------------------
    # 9) Print final IDs of atoms in CM_FIX
    # ------------------------------------------------------------------
    print("")
    print("=== FINAL CM_FIX atom IDs (to be fixed in the cluster model) ===")
    cmd.iterate(cm_fix_sel, "print(ID)")
    print("=================================================================")
    print(f"Total fixed atoms (CM_FIX): {cmd.count_atoms(cm_fix_sel)}")
    print("")
    print(f"Cluster model preparation complete.")
    print(f"  - Working CM object: {cm_obj}")
    print(f"  - Fixing selection: {cm_fix_sel} (atoms in sphere representation)")

# Make available as a PyMOL command
cmd.extend("make_cluster_model", make_cluster_model)

