# SPDX-License-Identifier: Apache-2.0
# ============================================================
# NeuroCrunch Script Template
# ============================================================
#
# HOW TO USE THIS TEMPLATE
# -------------------------
# 1. Copy this entire _template/ folder and rename it to your script name.
#    Example:  scripts/my_analysis/
# 2. Rename this file to match the folder name exactly.
#    Example:  my_analysis.py
# 3. Edit config.json to describe your parameters and outputs.
# 4. Fill in the run(params) function below with your analysis code.
# 5. Restart NeuroCrunch — your script appears in the scripts table.
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
import pandas as pd


def run(params):
    """
    Entry point called by the app for every pipeline execution.

    Parameters
    ----------
    params : dict
        Every key corresponds to a parameter name declared in config.json.
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
    # ----------------------------------------------------------------

    # type: "file"  →  absolute path string chosen by the user
    input_file = params["input_file"]

    # type: "directory"  →  absolute path string to a folder
    output_dir = params["output_dir"]

    # type: "string"  →  plain str  (single-line text field)
    label_text = params.get("label_text", "")

    # type: "text"  →  plain str  (multi-line text area)
    notes = params.get("notes", "")

    # type: "int"  →  Python int
    frame_count = int(params.get("frame_count", 100))

    # type: "float"  →  Python float
    threshold = float(params.get("threshold", 0.5))

    # type: "bool"  →  Python True or False
    normalize = bool(params.get("normalize", False))

    # type: "choice"  →  one of the strings listed in "options"
    method = params.get("method", "mean")   # e.g. "mean", "median", "max"

    # type: "file" with "link"  →  auto-filled from a previous script's output
    # The value is an absolute path string, same as any other "file" parameter.
    linked_csv = params.get("linked_csv", "")


    # ----------------------------------------------------------------
    # LOGGING — use print() freely
    # Every print() call appears as a new timestamped line in the app log.
    # ----------------------------------------------------------------

    print(f"Starting '{label_text}'")
    print(f"  Input : {input_file}")
    print(f"  Output: {output_dir}")
    print(f"  Method: {method}  |  threshold={threshold}  |  frames={frame_count}")
    if notes:
        print(f"  Notes : {notes}")


    # ----------------------------------------------------------------
    # ERROR HANDLING — raise an exception, never call sys.exit()
    # The app catches the exception, shows the message in the log,
    # and stops the pipeline cleanly without crashing.
    # ----------------------------------------------------------------

    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    os.makedirs(output_dir, exist_ok=True)


    # ----------------------------------------------------------------
    # PROGRESS — print("PROGRESS:<number>") to update the progress bar
    # The number is 0–100. You can emit as many updates as you like.
    # Regular print() calls continue to appear in the log as normal.
    # ----------------------------------------------------------------

    df = pd.read_csv(input_file)
    total = len(df)

    results = []
    for i, row in df.iterrows():
        # --- your per-row processing here ---
        value = row.iloc[0]   # placeholder
        if method == "mean":
            result = float(np.mean(df.iloc[:, 0]))
        elif method == "median":
            result = float(np.median(df.iloc[:, 0]))
        else:   # "max"
            result = float(np.max(df.iloc[:, 0]))
        results.append(result)

        # Emit progress every 10 % of rows processed
        if total > 0 and (i + 1) % max(1, total // 10) == 0:
            pct = (i + 1) / total * 100
            print(f"PROGRESS:{pct:.0f}")          # updates the progress bar
            print(f"  Processed {i + 1}/{total} rows...")  # appears in log

    print("PROGRESS:100")


    # ----------------------------------------------------------------
    # OPTIONAL: cooperative cancellation via ctx
    # If you declare run(params, ctx) the app passes a context object.
    # Check ctx.is_cancelled() inside long loops to stop early when the
    # user presses the Stop button.
    # ----------------------------------------------------------------
    #
    # def run(params, ctx):          ← change the signature
    #     for i, row in df.iterrows():
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
    ax.plot(results)
    ax.set_title(label_text)
    ax.set_xlabel('Row')
    ax.set_ylabel('Value')

    figures_dir = os.path.join(output_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)
    fig_path = os.path.join(figures_dir, 'result.png')
    fig.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close(fig)                  # always close to free memory
    print(f"Figure saved: {fig_path}")


    # ----------------------------------------------------------------
    # SAVE RESULTS
    # ----------------------------------------------------------------

    out_df = pd.DataFrame({'result': results})
    if normalize:
        std = out_df['result'].std()
        if std > 0:
            out_df['result'] = (out_df['result'] - out_df['result'].mean()) / std
        print("  Z-score normalization applied.")

    result_path = os.path.join(output_dir, 'result.csv')
    out_df.to_csv(result_path, index=False)
    print(f"CSV saved: {result_path}")


    # ----------------------------------------------------------------
    # RETURN OUTPUTS
    # Keys must match the 'outputs' object in config.json exactly.
    # Other scripts can link to these values using:
    #   "link": "<this_script_folder_name>.<output_key>"
    # ----------------------------------------------------------------

    return {
        "result_csv":  result_path,
        "figures_dir": figures_dir,
    }


# ============================================================
# CLI BLOCK
# This block only runs when you call the script from a terminal:
#   python my_analysis.py --input_file data.csv --output_dir ./out
# The app never enters this block (__name__ is not '__main__').
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_file",  required=True)
    parser.add_argument("--output_dir",  required=True)
    parser.add_argument("--label_text",  default="CLI run")
    parser.add_argument("--notes",       default="")
    parser.add_argument("--frame_count", type=int,   default=100)
    parser.add_argument("--threshold",   type=float, default=0.5)
    parser.add_argument("--normalize",   action="store_true")
    parser.add_argument("--method",      default="mean",
                        choices=["mean", "median", "max"])
    parser.add_argument("--linked_csv",  default="")
    args = parser.parse_args()
    run(vars(args))
