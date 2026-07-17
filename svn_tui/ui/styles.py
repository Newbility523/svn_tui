from __future__ import annotations


APP_CSS = """
    Screen {
        layout: vertical;
    }

    NavigationBar {
        width: 1fr;
        height: 1;
        background: $panel;
    }

    #content {
        height: 1fr;
    }

    #main {
        width: 1fr;
        height: 1fr;
    }

    #status-header {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #status-list {
        width: 1fr;
        height: 1fr;
    }

    #details {
        height: 7;
        padding: 1 0 0 0;
        border-top: solid $surface;
    }

    #operation-output-title {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #operation-output {
        width: 1fr;
        height: 6;
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    #side {
        width: 1fr;
        padding: 1 2;
        border-left: solid $surface;
    }

    #preview-title {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    #preview,
    #diff-preview {
        width: 1fr;
        height: 1fr;
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    StatusRow {
        height: 1;
    }

    CommitMessageDialog {
        align: center middle;
    }

    #commit-dialog {
        width: 76;
        height: 18;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #commit-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #commit-message {
        height: 7;
        margin-top: 1;
    }

    #commit-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
        align: right bottom;
    }

    #commit-actions Button {
        height: 3;
        margin-left: 1;
    }

    #commit-cancel {
        width: 14;
    }

    #commit-confirm {
        width: 24;
    }

    ConfirmActionDialog {
        align: center middle;
    }

    #confirm-dialog {
        width: 74;
        max-width: 94%;
        height: 18;
        max-height: 100%;
        padding: 1 2;
        background: $surface;
        border: solid $error;
    }

    #confirm-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #confirm-message {
        height: 1fr;
        min-height: 1;
        margin-top: 1;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
    }

    #confirm-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
        align: right bottom;
    }

    #confirm-actions Button {
        height: 3;
        margin-left: 1;
    }

    #confirm-cancel {
        width: 14;
    }

    #confirm-ok {
        width: 24;
    }

    HelpDialog {
        align: center middle;
    }

    #help-dialog {
        width: 78;
        height: 23;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #help-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #help-content {
        height: 1fr;
        margin-top: 1;
    }

    SvnCommandDialog {
        align: center middle;
    }

    #svn-command-dialog {
        width: 92%;
        height: 82%;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #svn-command-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #svn-command-top {
        height: 7;
        margin-top: 1;
        border: solid $surface-lighten-1;
    }

    #svn-command-command-title {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
        text-style: bold;
    }

    #svn-command-command {
        height: 1fr;
        padding: 0 1;
        overflow-x: auto;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
    }

    #svn-command-bottom {
        height: 1fr;
        margin-top: 1;
        border: solid $surface-lighten-1;
    }

    #svn-command-output-title {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
        text-style: bold;
    }

    #svn-command-output {
        height: 1fr;
        padding: 1;
        overflow-y: auto;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    #svn-command-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
        align: right bottom;
    }

    #svn-command-status {
        width: 1fr;
        height: 3;
        content-align: left middle;
    }

    #svn-command-actions Button {
        height: 3;
        margin-left: 1;
    }

    #svn-command-keep-running {
        width: 18;
    }

    #svn-command-confirm-cancel {
        width: 30;
    }

    #svn-command-cancel {
        width: 18;
    }

    LogScreen {
        layout: vertical;
        layers: base overlay;
    }

    StatusScreen {
        layers: base overlay;
    }

    #log-banner {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #log-body {
        height: 1fr;
    }

    #log-left {
        width: 40%;
        min-width: 36;
    }

    #log-right {
        width: 1fr;
        border-left: solid $surface;
        padding: 0 1;
    }

    .log-pane {
        height: 1fr;
    }

    #log-list-pane {
        height: 2fr;
        border-bottom: solid $surface;
    }

    #log-message-pane {
        height: 7;
        border-bottom: solid $surface;
    }

    #log-files-pane {
        height: 1fr;
    }

    .log-pane-title {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #log-list-header,
    #log-file-list-header {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }

    #log-message {
        height: 1fr;
    }

    #log-preview-title {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    #log-list,
    #log-file-list,
    #log-preview {
        width: 1fr;
        height: 1fr;
    }

    #status-search-label,
    #log-search-label,
    #log-file-search-label,
    #status-search,
    #log-search,
    #log-file-search {
        height: 1;
        width: 1fr;
        border: none;
        padding: 0;
        background: $panel;
        color: $text-muted;
    }

    #status-search:focus,
    #log-search:focus,
    #log-file-search:focus {
        border: none;
        background: $panel;
    }

    #status-search > .input--placeholder,
    #log-search > .input--placeholder,
    #log-file-search > .input--placeholder {
        color: $text-muted;
    }

    #log-preview {
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    #log-action-menu,
    #log-copy-menu {
        layer: overlay;
        position: absolute;
        background: $surface;
        border: solid $primary;
    }

    #status-action-popup {
        layer: overlay;
        position: absolute;
        background: $surface;
        border: solid $primary;
    }

    #status-action-title {
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: $primary;
        color: $text;
        text-style: bold;
        content-align: center middle;
    }

    #status-action-menu {
        width: 1fr;
        border: none;
        background: $surface;
        scrollbar-visibility: hidden;
    }

    #log-action-menu {
        width: 24;
        height: 3;
    }

    #log-copy-menu {
        width: 18;
        height: 5;
    }

    LogEntryRow,
    LogPathRow,
    OverlayMenuItem {
        height: 1;
    }

    ShelfSaveDialog,
    ExportPatchDialog {
        align: center middle;
    }

    #shelf-save-dialog,
    #export-patch-dialog {
        width: 78;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #shelf-save-title,
    #export-patch-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }

    .shelf-input-label {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }

    #shelf-name-input,
    #shelf-note-input,
    #export-patch-input {
        height: 3;
    }

    #shelf-save-actions,
    #export-patch-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
        align: right bottom;
    }

    #shelf-save-actions Button,
    #export-patch-actions Button {
        height: 3;
        width: auto;
        min-width: 16;
        margin-left: 1;
    }

    ShelfManagerScreen {
        layout: vertical;
    }

    #shelf-banner {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #shelf-body {
        height: 1fr;
    }

    .shelf-pane {
        height: 1fr;
        border-right: solid $surface;
    }

    #shelf-list-pane {
        width: 34%;
        min-width: 30;
    }

    #shelf-version-pane {
        width: 28%;
        min-width: 26;
    }

    #shelf-detail-pane {
        width: 1fr;
        border-right: none;
    }

    .shelf-pane-title {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #shelf-list,
    #shelf-version-list,
    #shelf-patch-preview {
        width: 1fr;
        height: 1fr;
    }

    #shelf-detail {
        height: 12;
        padding: 1;
        overflow-y: auto;
    }

    #shelf-operation-status {
        height: 2;
        padding: 0 1;
        background: $panel;
    }

    ShelfRow,
    ShelfVersionRow {
        height: 2;
    }
"""
