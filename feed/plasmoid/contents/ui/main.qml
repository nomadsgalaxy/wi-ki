/*
 * Desk Kiosk: a tray button for the desk kiosk, in the kiosk's own look.
 *
 * Click it for what's on the kiosk now, a picture of every page in its rotation (the last time each was on screen) to
 * jump to, Auto, Next, Update and the setup page, and the transitions to turn on and off. Middle-click skips to the
 * next page. Along the top: the screens this computer has paired with, to pick one, and the ones nearby to pair with
 * (kiosk-ctl pair asks for the shared key in a box of its own, so it's never on a command line).
 *
 * The work lives in kiosk-ctl (feed/kiosk-ctl in the Wi-Ki repo, linked into ~/.local/bin). This only runs it:
 * `status` when the popup opens and every few seconds while it's open, `thumbs` and `transitions` when it opens (and
 * the pictures again every half minute), and `show <page>`, `auto`, `next`, `update` or `transition <name> on|off` on
 * a click; `paired` and `screens` when it opens, and `pair <address>`. A screen other than the default one is picked
 * with KIOSK_SCREEN=<card id>.
 * The pages and transitions come from the kiosk, so new ones show up here without touching this file.
 */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Window

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
    property bool waiting: false   // a command is on its way ("busy" is the widget's own, a spinner)
    property var version: ({})     // commit, latest, behind, and the render server's, from status
    property var paired: []        // card IDs, from kiosk-ctl paired
    property var nearby: []        // {name, address, id, ...}, from kiosk-ctl screens
    property string pairing: ""    // the address it's pairing with, while it is
    readonly property string chosen: Plasmoid.configuration.screen
    // the popup's unit: Plasma's own on a big screen, smaller on a laptop, so it fits in about half the width and
    // most of the height (64 units across, about 44 down with a full rotation)
    readonly property real u: Kirigami.Units.gridUnit * Math.min(1, Screen.desktopAvailableWidth * 0.55 / (64 * Kirigami.Units.gridUnit),
                                                                 Screen.desktopAvailableHeight * 0.85 / (44 * Kirigami.Units.gridUnit))

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
            const m = source.match(/^(?:KIOSK_SCREEN=(\S+) )?\S+ (.*)$/);
            const ask = m[2];
            if (ask === "paired") {
                root.paired = out === "" ? [] : out.split("\n");
                if (root.chosen === "" && root.paired.length > 0 && root.paired[0] !== "default") {
                    root.pick(root.paired[0]);
                }
                return;
            } else if (ask === "screens") {
                root.nearby = out.split("\n").filter(line => line !== "").map(line => JSON.parse(line));
                return;
            } else if (ask.startsWith("pair ")) {
                root.pairing = "";
                const id = (out.match(/paired with (k-[0-9a-f]{6})/) || [])[1];
                root.error = id ? "" : (failed || i18n("Didn't pair"));
                if (id) {
                    root.pick(id);
                }
                root.ask("paired");
                return;
            }
            if ((m[1] || "") !== root.chosen) {
                return;   // an answer from the screen it was on before
            }
            try {
                if (ask === "status") {
                    const s = JSON.parse(out);
                    root.pages = s.pages;
                    root.showing = s.showing || "";
                    root.pinned = s.pinned || "";
                    root.version = s;
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
                    root.waiting = false;
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
        exec.connectSource((root.chosen !== "" ? "KIOSK_SCREEN=" + root.chosen + " " : "") + root.ctl + " " + what);
    }

    function pick(id) {
        Plasmoid.configuration.screen = id;
        root.pages = []; root.showing = ""; root.pinned = ""; root.thumbs = {}; root.themes = []; root.version = {};
        root.waiting = false;
        refresh();
    }

    function pair(address) {
        // plain addresses only: it goes on a command line
        if (root.pairing !== "" || !/^[A-Za-z0-9.:-]+$/.test(address)) {
            return;
        }
        root.pairing = address;
        exec.connectSource(root.ctl + " pair " + address);
    }

    function screenName(id) {
        if (id === "default") {
            return i18n("Default");
        }
        const found = root.nearby.find(s => s.id === id);
        return found ? found.name : id;
    }

    // how far behind GitHub's main the kiosk (and its render server) is, as it last looked
    function behind() {
        return (root.version.behind || 0) + ((root.version.server || {}).behind || 0);
    }

    function send(command) {
        if (root.waiting) {
            return;
        }
        root.waiting = true;
        ask(command);
    }

    function refresh() {
        ask("status");
        ask("thumbs");
        ask("transitions");
    }

    Component.onCompleted: ask("status")
    onExpandedChanged: if (expanded) { refresh(); ask("paired"); ask("screens"); }

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
        property bool usable: !root.waiting
        signal pressed()

        implicitHeight: root.u * 2.6
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
            font.pixelSize: root.u * 1.15
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

        // sized from its parts, never from itself: a popup bound to its own implicitHeight grows a little each layout.
        // The tray only honours a widget's minimum size, so that's set too, or it shrinks the popup to its own default
        Layout.minimumWidth: root.u * 64
        Layout.preferredWidth: Layout.minimumWidth
        Layout.minimumHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2
        Layout.preferredHeight: Layout.minimumHeight
        Layout.maximumHeight: Layout.minimumHeight

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
                    font.pixelSize: root.u * 1.0
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: root.toolTipSubText.toUpperCase()
                    color: root.error !== "" ? root.amber : root.starlight
                    font.family: root.mono
                    font.pixelSize: root.u * 1.6
                    font.bold: true
                }
            }

            Text {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                text: "// SCREENS"
                color: root.cyan
                font.family: root.mono
                font.pixelSize: root.u * 1.0
            }

            // the screens paired with, to pick one; the ones nearby that aren't, and any address, to pair with
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root.paired

                    KioskButton {
                        required property string modelData
                        label: root.screenName(modelData).toUpperCase()
                        lit: root.chosen === modelData || (modelData === "default" && root.chosen === "")
                        usable: true
                        onPressed: root.pick(modelData)
                    }
                }
                Repeater {
                    model: root.nearby.filter(s => root.paired.indexOf(s.id) < 0)

                    KioskButton {
                        required property var modelData
                        label: "+ PAIR " + modelData.name.toUpperCase()
                        usable: root.pairing === ""
                        onPressed: root.pair(modelData.address)
                    }
                }
                QQC2.TextField {
                    id: address
                    implicitHeight: root.u * 2.6
                    implicitWidth: root.u * 12
                    placeholderText: i18n("or an address")
                    font.family: root.mono
                    onAccepted: root.pair(text)
                }
                KioskButton {
                    label: root.pairing !== "" ? "PAIRING…" : "PAIR"
                    usable: root.pairing === "" && address.text !== ""
                    onPressed: root.pair(address.text)
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
                font.pixelSize: root.u * 1.0
            }

            // a picture of each page, the last time it was on: click to jump there and stay
            GridLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                columns: 4   // four across, so the whole rotation fits above a panel
                columnSpacing: Kirigami.Units.smallSpacing
                rowSpacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root.pages

                    Rectangle {
                        id: tile
                        required property string modelData

                        Layout.fillWidth: true
                        Layout.preferredWidth: 1   // the columns the same width
                        Layout.preferredHeight: shot.height + 4   // the picture's own shape; its name goes over it
                        color: root.raised
                        border.color: root.showing === modelData ? root.cyan : tileHover.containsMouse ? root.dust : root.rule
                        border.width: root.showing === modelData ? 2 : 1
                        opacity: root.waiting ? 0.6 : 1

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
                        Rectangle {   // a dark strip along the picture's bottom, for its name
                            anchors { left: shot.left; right: shot.right; bottom: shot.bottom }
                            height: name.implicitHeight + 4
                            color: Qt.rgba(root.space.r, root.space.g, root.space.b, 0.8)
                        }
                        RowLayout {
                            anchors { left: shot.left; right: shot.right; bottom: shot.bottom; margins: 2; leftMargin: 4 }
                            spacing: 2
                            Text {
                                id: name
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: root.title(tile.modelData)
                                color: root.showing === tile.modelData ? root.cyan : root.starlight
                                font.family: root.mono
                                font.pixelSize: root.u * 1.0
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
                            enabled: !root.waiting
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
                    usable: !root.waiting && root.pinned !== ""
                    onPressed: root.send("auto")
                }
                KioskButton {
                    label: "NEXT ›"
                    usable: !root.waiting && root.pages.length > 0
                    onPressed: root.send("next")
                }
                KioskButton {
                    // behind is as of its last look (every 10 minutes), so up to date still offers to look now
                    readonly property string refused: root.version.refused || (root.version.server || {}).refused || ""
                    label: !root.version.commit ? "UPDATE"
                        : refused !== "" ? "REFUSED " + refused + " · CHECK NOW"
                        : root.behind() > 0 ? "UPDATE · " + root.behind() + " BEHIND"
                        : "UP TO DATE " + root.version.commit + " · CHECK NOW"
                    lit: root.behind() > 0
                    onPressed: root.send("update")
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
                font.pixelSize: root.u * 1.0
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
