# SPDX-License-Identifier: Apache-2.0
# ============================================================
# NeuroCrunch Script Template
# ============================================================
#
# HOW TO USE THIS TEMPLATE
# -------------------------
# 1. Copy this entire template/ folder and rename it to your script name.
#    Example:  scripts/my_analysis/   (or into your user scripts folder)
# 2. Rename this file to match the folder name exactly.
#    Example:  my_analysis.py
# 3. Edit config.json to describe your parameters and outputs.
# 4. Fill in the run(params) function below with your analysis code.
# 5. Press Refresh (or restart NeuroCrunch) — your script appears in the
#    scripts table.
#
# NOTES ON config.json
# --------------------------------------------------------------------
# - 'id' and 'entry_point' are OPTIONAL. When omitted they are derived from
#   the folder name (id = folder name, entry_point = <folder name>.py), which
#   is why renaming the folder and this file together is all you need.
# - 'version' and 'author' are optional metadata shown in the script's tooltip.
# - 'category' is a free-text label you choose to group your scripts.
# - Every parameter type and option is demonstrated in the accompanying
#   config.json. Double-click the template row in the app to see them rendered.
#
# AVAILABLE LIBRARIES (bundled — no installation required)
# ---------------------------------------------------------
# numpy         — arrays and numerical operations
# pandas        — dataframes, CSV/Excel I/O
# scipy         — signal processing, statistics, linear algebra
# cv2           — video and image I/O (opencv-python)
# matplotlib    — plotting (use savefig, NOT show)
# tifffile      — TIFF stack reading/writing
# skimage       — image processing (scikit-image)
# read_roi      — ImageJ/FIJI ROI file reading
#
# ============================================================

import os
import numpy as np


def run(params):
    """
    Entry point called by the app for every pipeline execution.

    Parameters
    ----------
    params : dict
        Every key corresponds to a parameter 'name' declared in config.json.
        Values are already the correct Python type (int, float, bool, str).

    Returns
    -------
    dict
        Keys must match the 'outputs' object declared in config.json.
        Values are typically absolute file paths (strings).
    """

    # ----------------------------------------------------------------
    # READING PARAMETERS
    # Each type comes in as a native Python value — no conversion needed.
    # Use params.get(name, fallback) for anything that is optional.
    # ----------------------------------------------------------------

    # type: "string"  →  plain str  (single-line text field)
    text_input = params.get("text_input", "")

    # type: "text"  →  plain str  (multi-line text area)
    long_text_input = params.get("long_text_input", "")

    # type: "int"  →  Python int  (with min/max limits in config.json)
    whole_number = int(params.get("whole_number", 10))

    # type: "int"  →  Python int  (no min/max declared — any integer)
    whole_number_unbounded = int(params.get("whole_number_unbounded", 0))

    # type: "float"  →  Python float  (min/max/decimals in config.json)
    decimal_number = float(params.get("decimal_number", 0.25))

    # type: "bool"  →  Python True or False
    checkbox_option = bool(params.get("checkbox_option", True))

    # type: "choice"  →  one of the strings listed in "options"
    dropdown_option = params.get("dropdown_option", "first option")

    # type: "file"  →  absolute path string chosen by the user (required)
    file_input = params["file_input"]

    # type: "file" without extensions  →  absolute path string (optional)
    file_input_any_type = params.get("file_input_any_type", "")

    # type: "directory"  →  absolute path string to a folder (required)
    folder_input = params["folder_input"]

    # type: "string" with a localized label/description  →  plain str
    localized_example = params.get("localized_example", "")

    # type: "file" with "link"  →  auto-filled from a previous script's output.
    # The value is an absolute path string, same as any other "file" parameter.
    linked_file_input = params.get("linked_file_input", "")


    # ----------------------------------------------------------------
    # LOGGING — use print() freely
    # Every print() call appears as a new timestamped line in the app log.
    # ----------------------------------------------------------------

    print(f"Text input        : {text_input}")
    print(f"Whole number      : {whole_number}  (unbounded: {whole_number_unbounded})")
    print(f"Decimal number    : {decimal_number}")
    print(f"Checkbox          : {checkbox_option}")
    print(f"Dropdown          : {dropdown_option}")
    print(f"File input        : {file_input}")
    print(f"Folder input      : {folder_input}")
    if long_text_input:
        print(f"Notes             : {long_text_input}")
    if linked_file_input:
        print(f"Linked file       : {linked_file_input}")


    # ----------------------------------------------------------------
    # ERROR HANDLING — raise an exception, never call sys.exit()
    # The app catches the exception, shows the message in the log,
    # and stops the pipeline cleanly without crashing.
    # ----------------------------------------------------------------

    if not os.path.isfile(file_input):
        raise FileNotFoundError(f"File input not found: {file_input}")

    os.makedirs(folder_input, exist_ok=True)


    # ----------------------------------------------------------------
    # PROGRESS — print("PROGRESS:<number>") to update the progress bar
    # The number is 0–100. You can emit as many updates as you like.
    # Regular print() calls continue to appear in the log as normal.
    # ----------------------------------------------------------------

    steps = max(1, whole_number)
    for i in range(steps):
        # --- replace this with your real per-step processing ---
        pct = (i + 1) / steps * 100
        print(f"PROGRESS:{pct:.0f}")               # updates the progress bar
        print(f"  Step {i + 1}/{steps} done...")   # appears in the log

    print("PROGRESS:100")


    # ----------------------------------------------------------------
    # OPTIONAL: cooperative cancellation via ctx
    # If you declare run(params, ctx) the app passes a context object.
    # Check ctx.is_cancelled() inside long loops to stop early when the
    # user presses the Stop button.
    # ----------------------------------------------------------------
    #
    # def run(params, ctx):          ← change the signature
    #     for i in range(steps):
    #         if ctx.is_cancelled():
    #             print("Cancelled by user.")
    #             return {}          ← return empty dict to stop cleanly
    #         ...
    #
    # ctx.progress(50)               ← same as print("PROGRESS:50")
    # ctx.log("some message")        ← same as print("some message")


    # ----------------------------------------------------------------
    # OPTIONAL: plotting with matplotlib
    # Never call plt.show() — it blocks the thread.
    # Always save figures to disk with savefig and return the path.
    # ----------------------------------------------------------------

    import matplotlib
    matplotlib.use('Agg')           # non-interactive backend — required
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot(np.arange(steps))
    ax.set_title(text_input or "Script template")
    ax.set_xlabel('Step')
    ax.set_ylabel('Value')

    figures_dir = os.path.join(folder_input, 'figures')
    os.makedirs(figures_dir, exist_ok=True)
    fig_path = os.path.join(figures_dir, 'result.png')
    fig.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close(fig)                  # always close to free memory
    print(f"Figure saved: {fig_path}")


    # ----------------------------------------------------------------
    # SAVE RESULTS
    # Write your real outputs here. This example just records the chosen
    # parameters so the run produces something inspectable.
    # ----------------------------------------------------------------

    summary_path = os.path.join(folder_input, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as fh:
        fh.write(f"text_input       = {text_input}\n")
        fh.write(f"whole_number     = {whole_number}\n")
        fh.write(f"decimal_number   = {decimal_number}\n")
        fh.write(f"checkbox_option  = {checkbox_option}\n")
        fh.write(f"dropdown_option  = {dropdown_option}\n")
        if checkbox_option:
            fh.write("normalize        = applied\n")
    print(f"Summary saved: {summary_path}")


    # ----------------------------------------------------------------
    # RETURN OUTPUTS
    # Keys must match the 'outputs' object in config.json exactly.
    # Other scripts can link to these values using:
    #   "link": "<this_script_folder_name>.<output_key>"
    # ----------------------------------------------------------------

    return {
        "output_file":   summary_path,
        "output_folder": figures_dir,
    }


# ============================================================
# CLI BLOCK
# This block only runs when you call the script from a terminal:
#   python my_analysis.py --file_input data.csv --folder_input ./out
# The app never enters this block (__name__ is not '__main__').
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text_input",            default="CLI run")
    parser.add_argument("--long_text_input",       default="")
    parser.add_argument("--whole_number",          type=int,   default=10)
    parser.add_argument("--whole_number_unbounded", type=int,  default=0)
    parser.add_argument("--decimal_number",        type=float, default=0.25)
    parser.add_argument("--checkbox_option",       action="store_true")
    parser.add_argument("--dropdown_option",       default="first option",
                        choices=["first option", "second option", "third option"])
    parser.add_argument("--file_input",            required=True)
    parser.add_argument("--file_input_any_type",   default="")
    parser.add_argument("--folder_input",          required=True)
    parser.add_argument("--localized_example",     default="")
    parser.add_argument("--linked_file_input",     default="")
    args = parser.parse_args()
    run(vars(args))
