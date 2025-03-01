import tkinter as tk
from tkinter import filedialog, ttk


def create_interface() -> None:
    # Initialize main window
    root = tk.Tk()
    root.title("Example")
    root.geometry("600x400")  # Set window size
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    # # Toolbar Frame
    # toolbar = tk.Frame(root, relief=tk.RAISED, bd=2)
    # toolbar.pack(side=tk.TOP, fill=tk.X)

    # # Toolbar Buttons
    # new_button = tk.Button(toolbar, text="New", command=lambda: print("New"))
    # new_button.pack(side=tk.LEFT, padx=2, pady=2)

    # open_button = tk.Button(toolbar, text="Open",
    #                         command=lambda: filedialog.askopenfilename())
    # open_button.pack(side=tk.LEFT, padx=2, pady=2)

    # save_button = tk.Button(toolbar, text="Save", command=lambda: print("Save"))
    # save_button.pack(side=tk.LEFT, padx=2, pady=2)

    # apply_button = tk.Button(toolbar, text="Apply Pipe", command=lambda: print("Apply Pipe"))
    # apply_button.pack(side=tk.LEFT, padx=2, pady=2)

    # Pipe Settings Frame
    frame_pipe = ttk.LabelFrame(root, text="Pipe")
    frame_pipe.grid(sticky="nsew", row=0, column=0, padx=10, pady=10)
    frame_pipe.columnconfigure(0, weight=1)
    frame_pipe.rowconfigure(0, weight=1)

    # Name Entry
    ttk.Label(frame_pipe, text="Name").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    name_entry = ttk.Entry(frame_pipe)
    name_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

    # Export File Button
    ttk.Label(frame_pipe, text="Export File").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    export_entry = ttk.Entry(frame_pipe)
    export_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
    export_button = ttk.Button(
        frame_pipe, text="...", command=lambda: filedialog.askopenfilename()
    )
    export_button.grid(row=1, column=2, padx=5, pady=5)

    frame_pipe.columnconfigure(1, weight=1)

    # Main Pipe Settings
    main_pipe_frame = ttk.LabelFrame(frame_pipe, text="Main Pipe")
    main_pipe_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
    main_pipe_frame.columnconfigure(1, weight=1)

    ttk.Label(main_pipe_frame, text="Radius").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    radius_main = ttk.Entry(main_pipe_frame)
    radius_main.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

    ttk.Label(main_pipe_frame, text="Width").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    width_main = ttk.Entry(main_pipe_frame)
    width_main.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

    ttk.Label(main_pipe_frame, text="Half Length").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    half_length_main = ttk.Entry(main_pipe_frame)
    half_length_main.grid(row=2, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

    # Incident Pipe Settings
    incident_pipe_frame = ttk.LabelFrame(frame_pipe, text="Incident Pipe")
    incident_pipe_frame.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
    incident_pipe_frame.columnconfigure(1, weight=1)

    ttk.Label(incident_pipe_frame, text="Radius").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    radius_incident = ttk.Entry(incident_pipe_frame)
    radius_incident.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    ttk.Label(incident_pipe_frame, text="Width").grid(
        row=1, column=0, padx=5, pady=5, sticky="w"
    )
    width_incident = ttk.Entry(incident_pipe_frame)
    width_incident.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

    ttk.Label(incident_pipe_frame, text="Half Length").grid(
        row=2, column=0, padx=5, pady=5, sticky="w"
    )
    half_length_incident = ttk.Entry(incident_pipe_frame)
    half_length_incident.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

    # Edge Type
    edge_type_frame = ttk.LabelFrame(frame_pipe, text="Edge Type")
    edge_type_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

    edge_type_var = tk.StringVar(value="Normal")
    ttk.Radiobutton(
        edge_type_frame, text="Normal", variable=edge_type_var, value="Normal"
    ).grid(
        row=0, column=0, padx=5, pady=5, sticky="ew"
    )  # .pack(side="left", padx=5, pady=5)
    ttk.Radiobutton(
        edge_type_frame, text="Chamfer", variable=edge_type_var, value="Chamfer"
    ).grid(
        row=0, column=1, padx=5, pady=5, sticky="ew"
    )  # .pack(side="left", padx=5, pady=5)
    ttk.Radiobutton(
        edge_type_frame, text="Fillet", variable=edge_type_var, value="Fillet"
    ).grid(
        row=0, column=2, padx=5, pady=5, sticky="ew"
    )  # .pack(side="left", padx=5, pady=5)

    root.grid_propagate()
    root.mainloop()


# Run the interface
create_interface()
