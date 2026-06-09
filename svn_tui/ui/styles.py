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
        height: 13;
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
        height: 5;
        margin-top: 1;
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

    TextInputDialog {
        align: center middle;
    }

    #text-input-dialog {
        width: 68;
        height: 10;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    #text-input-title {
        height: 1;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
    }

    #text-input-value {
        height: 3;
        margin-top: 1;
    }

    #text-input-actions {
        width: 1fr;
        height: 3;
        align: right bottom;
    }

    #text-input-actions Button {
        height: 3;
        margin-left: 1;
    }

    #text-input-cancel {
        width: 14;
    }

    #text-input-confirm {
        width: 24;
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

    ShelfManagerScreen {
        layout: vertical;
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

    #shelf-left {
        width: 34%;
        min-width: 32;
        border-right: solid $surface;
    }

    #shelf-middle {
        width: 28%;
        min-width: 28;
        border-right: solid $surface;
    }

    #shelf-right {
        width: 1fr;
        padding: 0 1;
    }

    .shelf-pane {
        height: 1fr;
    }

    .shelf-pane-title {
        height: 1;
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }

    #shelf-pending {
        height: 4;
        padding: 1 0;
        border-bottom: solid $surface;
    }

    #shelf-list,
    #shelf-version-list,
    #shelf-preview {
        width: 1fr;
        height: 1fr;
    }

    #shelf-preview-title {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    #shelf-preview {
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: visible;
    }

    #shelf-detail {
        height: 8;
        padding: 1 0 0 0;
        border-top: solid $surface;
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
    ShelfRow,
    ShelfVersionRow,
    OverlayMenuItem {
        height: 1;
    }
"""
