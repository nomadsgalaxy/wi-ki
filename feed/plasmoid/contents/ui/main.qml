/*
 * Desk Kiosk: a tray button for the desk kiosk, in the kiosk's own look.
 *
 * Click it for what's on the kiosk now, a picture of every page in its rotation (the last time each was on screen) to
 * jump to, Auto, Next and the setup page, and the transitions to turn on and off. Middle-click skips to the next page.
 *
 * The work lives in kiosk-ctl (feed/kiosk-ctl in the Wi-Ki repo, linked into ~/.local/bin). This only runs it:
 * `status` when the popup opens and every few seconds while it's open, `thumbs` and `transitions` when it opens (and
 * the pictures again every half minute), and `show <page>`, `auto`, `next` or `transition <name> on|off` on a click.
 * The pages and transitions come from the kiosk, so new ones show up here without touching this file.
 */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    readonly property string ctl: "kiosk-ctl"   // install.sh puts the full path in

    property var pages: []
    property string showing: ""
    property string pinned: ""
    property var thumbs: ({})
    property var themes: []   // the transitions installed ("transitions" is taken: every Item has one)
    property var off: []
    property string error: ""
    property bool busy: false

    // the kiosk's colours (kit.py): Deep Space, Raised Space, the Hairline, Warp Cyan, Starlight, Dust, Booster Amber
    readonly property color space: "#05060f"
    readonly property color raised: "#0a0c1f"
    readonly property color rule: "#1b323a"
    readonly property color cyan: "#7df9ff"
    readonly property color starlight: "#e8ecff"
    readonly property color dust: "#9aa3c7"
    readonly property color amber: "#ffce6a"
    readonly property string mono: "monospace"

    readonly property var titles: ({ weather: "Weather", github: "GitHub", agents: "Agents", nowplaying: "Now Playing",
                                     system: "System", radar: "Flight Radar", calendar: "Calendar", cfradar: "Cloudflare Radar",
                                     septa: "SEPTA", halflife3: "Half-Life 3", flyers: "Flyers", around: "Around", home: "Home",
                                     sports: "Sports", sky: "Sky", air: "Air", xkcd: "xkcd", nomadsgalaxy: "Nomads Galaxy",
                                     hive76: "Hive76", coreone: "Core One", johnny5: "Johnny 5", pacman: "Pac-Man",
                                     swanson: "Ron Swanson", xkcd_panel: "xkcd Panel" })

    function title(name) {
        return titles[name] || (name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " "));
    }

    function picture(name) {
        return thumbs[name] ? "data:image/jpeg;base64," + thumbs[name] : "";
    }

    Plasmoid.icon: pinned !== "" ? "window-pin" : "video-display"
    Plasmoid.status: PlasmaCore.Types.ActiveStatus

    toolTipMainText: i18n("Desk Kiosk")
    toolTipSubText: error !== "" ? error
        : showing === "" ? i18n("Not reached yet")
        : pinned !== "" ? i18n("Pinned to %1", title(pinned))
        : i18n("Showing %1, rotating", title(showing))

    Plasma5Support.DataSource {
        id: exec

        engine: "executable"
        connectedSources: []

        onNewData: function (source, data) {
            disconnectSource(source);
            const out = ((data["stdout"] || "") + "").trim();
            const failed = ((data["stderr"] || "") + "").trim().split("\n").pop();
            const ask = source.slice(root.ctl.length + 1);
            try {
                if (ask === "status") {
                    const s = JSON.parse(out);
                    root.pages = s.pages;
                    root.showing = s.showing || "";
                    root.pinned = s.pinned || "";
                    root.error = "";
                } else if (ask === "thumbs") {
                    root.thumbs = JSON.parse(out);
                } else if (ask === "transitions") {
                    const t = JSON.parse(out);
                    root.themes = t.all;
                    root.off = t.off;
                } else if (ask === "setup") {
                    Qt.openUrlExternally(out);
                } else {
                    // a change: ask again rather than assume (the kiosk switches pages within a quarter second, and
                    // a transition change restarts its display)
                    root.busy = false;
                    if (data["exit code"] !== 0) {
                        root.error = failed || i18n("The kiosk said no");
                    }
                    if (ask.startsWith("transition ")) {
                        root.ask("transitions");
                    }
                    statusSoon.restart();
                }
            } catch (e) {
                root.error = failed || i18n("Can't reach the kiosk");
            }
        }
    }

    function ask(what) {
        exec.connectSource(root.ctl + " " + what);
    }

    function send(command) {
        if (root.busy) {
            return;
        }
        root.busy = true;
        ask(command);
    }

    function refresh() {
        ask("status");
        ask("thumbs");
        ask("transitions");
    }

    Component.onCompleted: ask("status")
    onExpandedChanged: if (expanded) refresh()

    Timer {
        id: statusSoon
        interval: 600
        onTriggered: root.ask("status")
    }

    // Only while the popup is open: every ask is an SSH login on the kiosk or its render server.
    Timer {
        interval: 5000
        running: root.expanded
        repeat: true
        onTriggered: root.ask("status")
    }

    Timer {
        interval: 30000
        running: root.expanded
        repeat: true
        onTriggered: root.ask("thumbs")
    }

    compactRepresentation: MouseArea {
        id: compact

        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: function (mouse) {
            if (mouse.button === Qt.MiddleButton) {
                root.send("next");
            } else {
                root.expanded = !root.expanded;
            }
        }

        Kirigami.Icon {
            anchors.fill: parent
            source: Plasmoid.icon
            active: compact.containsMouse
            opacity: root.error !== "" ? 0.5 : 1.0
        }
    }

    // a button in the kiosk's look: a hairline box, cyan when it's on or pressed
    component KioskButton: Rectangle {
        id: button

        property string label
        property bool lit: false
        property bool usable: !root.busy
        signal pressed()

        implicitHeight: Kirigami.Units.gridUnit * 1.6
        implicitWidth: words.implicitWidth + Kirigami.Units.largeSpacing * 2
        radius: 2
        color: lit ? Qt.rgba(root.cyan.r, root.cyan.g, root.cyan.b, 0.14) : root.raised
        border.color: lit || hover.containsMouse ? root.cyan : root.rule
        border.width: 1
        opacity: usable ? 1 : 0.4

        Text {
            id: words
            anchors.centerIn: parent
            text: button.label
            color: button.lit ? root.cyan : root.starlight
            font.family: root.mono
            font.pixelSize: Kirigami.Units.gridUnit * 0.7
        }

        MouseArea {
            id: hover
            anchors.fill: parent
            hoverEnabled: true
            enabled: button.usable
            cursorShape: Qt.PointingHandCursor
            onClicked: button.pressed()
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        id: popup

        // sized from its parts, never from itself: a popup bound to its own implicitHeight grows a little each layout
        Layout.preferredWidth: Kirigami.Units.gridUnit * 34
        Layout.preferredHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2
        Layout.maximumHeight: Layout.preferredHeight

        background: Rectangle {   // the popup's own background slot: inside the layout, a box can't fill it
            color: root.space
            radius: 4
            border.color: root.rule
        }

        contentItem: ColumnLayout {
            id: content
            spacing: Kirigami.Units.largeSpacing

            // the heading, as the kiosk's pages have it: a ship's-log kicker, then where it stands
            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.largeSpacing
                Layout.bottomMargin: 0
                spacing: 2

                Text {
                    text: "// DESK KIOSK"
                    color: root.cyan
                    font.family: root.mono
                    font.pixelSize: Kirigami.Units.gridUnit * 0.6
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: root.toolTipSubText.toUpperCase()
                    color: root.error !== "" ? root.amber : root.starlight
                    font.family: root.mono
                    font.pixelSize: Kirigami.Units.gridUnit * 0.95
                    font.bold: true
                }
            }

            // what's on the kiosk now, big
            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.preferredHeight: width * 515 / 1920
                color: root.raised
                border.color: root.cyan
                border.width: 2
                visible: root.showing !== ""

                Image {
                    anchors.fill: parent
                    anchors.margins: 2
                    source: root.picture(root.showing)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
                Text {
                    anchors.centerIn: parent
                    visible: root.picture(root.showing) === ""
                    text: root.title(root.showing).toUpperCase()
                    color: root.dust
                    font.family: root.mono
                }
            }

            Text {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                text: "// PAGES"
                color: root.cyan
                font.family: root.mono
                font.pixelSize: Kirigami.Units.gridUnit * 0.6
            }

            // a picture of each page, the last time it was on: click to jump there and stay
            GridLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                columns: 3
                columnSpacing: Kirigami.Units.smallSpacing
                rowSpacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root.pages

                    Rectangle {
                        id: tile
                        required property string modelData

                        Layout.fillWidth: true
                        Layout.preferredWidth: 1   // the columns the same width
                        Layout.preferredHeight: shot.height + name.implicitHeight + 6
                        color: root.raised
                        border.color: root.showing === modelData ? root.cyan : tileHover.containsMouse ? root.dust : root.rule
                        border.width: root.showing === modelData ? 2 : 1
                        opacity: root.busy ? 0.6 : 1

                        Image {
                            id: shot
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 2 }
                            height: width * 515 / 1920
                            source: root.picture(tile.modelData)
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                        }
                        Rectangle {   // never drawn yet: just its name
                            anchors.fill: shot
                            visible: root.picture(tile.modelData) === ""
                            color: root.space
                        }
                        RowLayout {
                            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 3 }
                            spacing: 2
                            Text {
                                id: name
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: root.title(tile.modelData)
                                color: root.showing === tile.modelData ? root.cyan : root.starlight
                                font.family: root.mono
                                font.pixelSize: Kirigami.Units.gridUnit * 0.6
                            }
                            Kirigami.Icon {
                                visible: root.pinned === tile.modelData
                                source: "window-pin"
                                implicitWidth: Kirigami.Units.iconSizes.small
                                implicitHeight: implicitWidth
                            }
                        }
                        MouseArea {
                            id: tileHover
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !root.busy
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.send("show " + tile.modelData)
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.smallSpacing

                KioskButton {
                    Layout.fillWidth: true
                    label: root.pinned !== "" ? "AUTO: BACK TO THE ROTATION" : "ROTATING"
                    lit: root.pinned === ""
                    usable: !root.busy && root.pinned !== ""
                    onPressed: root.send("auto")
                }
                KioskButton {
                    label: "NEXT ›"
                    usable: !root.busy && root.pages.length > 0
                    onPressed: root.send("next")
                }
                KioskButton {
                    label: "SETTINGS ↗"
                    usable: true
                    onPressed: root.ask("setup")
                }
            }

            Text {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                text: "// TRANSITIONS · a change restarts the display"
                color: root.cyan
                font.family: root.mono
                font.pixelSize: Kirigami.Units.gridUnit * 0.6
            }

            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                Layout.bottomMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root.themes

                    KioskButton {
                        required property string modelData
                        readonly property bool on: root.off.indexOf(modelData) < 0

                        label: (on ? "■ " : "□ ") + root.title(modelData)
                        lit: on
                        onPressed: root.send("transition " + modelData + (on ? " off" : " on"))
                    }
                }
            }
        }
    }
}
