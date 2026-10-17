/*
 * Desk Kiosk: a tray button for picking what the desk kiosk shows.
 *
 * The work lives in kiosk-ctl (feed/kiosk-ctl in the Wi-Ki repo, linked into ~/.local/bin). This only runs it:
 * `status` when the popup opens and every few seconds while it's open, and `show <page>`, `auto` or `next` on a click.
 * The page list comes from the Pi's playlist, so a new page shows up here without touching this file.
 */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
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
    property string error: ""
    property bool busy: false

    readonly property var titles: ({ weather: "Weather", github: "GitHub", agents: "Agents", nowplaying: "Now Playing", system: "System",
                                     radar: "Flight Radar", calendar: "Calendar", cfradar: "Cloudflare Radar", septa: "SEPTA",
                                     halflife3: "Half-Life 3", flyers: "Flyers", around: "Around Hive76",
                                     "around-311": "Hive76 · 311", "around-building": "Hive76 · Building",
                                     "around-bikes": "Hive76 · Bikes", home: "Home", sports: "Philly Sports" })

    function title(page) {
        return titles[page] || (page.charAt(0).toUpperCase() + page.slice(1));
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
            if (source.endsWith(" status")) {
                try {
                    const s = JSON.parse(out);
                    root.pages = s.pages;
                    root.showing = s.showing || "";
                    root.pinned = s.pinned || "";
                    root.error = "";
                } catch (e) {
                    root.error = ((data["stderr"] || "") + "").trim().split("\n").pop() || i18n("Can't reach the kiosk");
                }
            } else {
                // A command finished; the kiosk switches within a quarter second, so ask again rather than assume.
                root.busy = false;
                if (data["exit code"] !== 0) {
                    root.error = ((data["stderr"] || "") + "").trim() || i18n("The kiosk said no");
                }
                statusSoon.restart();
            }
        }
    }

    function poll() {
        exec.connectSource(root.ctl + " status");
    }

    function send(command) {
        if (root.busy) {
            return;
        }
        root.busy = true;
        exec.connectSource(root.ctl + " " + command);
    }

    Component.onCompleted: poll()
    onExpandedChanged: if (expanded) poll()

    Timer {
        id: statusSoon
        interval: 600
        onTriggered: root.poll()
    }

    // Only while the popup is open: every status is an SSH login on a Pi Zero.
    Timer {
        interval: 5000
        running: root.expanded
        repeat: true
        onTriggered: root.poll()
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

    fullRepresentation: PlasmaExtras.Representation {
        id: popup

        // Sized from its parts, never from itself: a popup bound to its own implicitHeight grows a little each
        // layout and creeps down past the panel.
        Layout.preferredWidth: Kirigami.Units.gridUnit * 20
        Layout.preferredHeight: heading.implicitHeight + content.implicitHeight + Kirigami.Units.largeSpacing * 2
        Layout.maximumHeight: Layout.preferredHeight

        header: PlasmaExtras.PlasmoidHeading {
            id: heading
            PlasmaExtras.Heading {
                level: 3
                text: i18n("Desk Kiosk")
            }
        }

        contentItem: ColumnLayout {
            id: content
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                opacity: 0.7
                text: root.toolTipSubText
            }

            // two columns, so a long playlist doesn't make the popup taller than the space above the panel
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Kirigami.Units.smallSpacing
                rowSpacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root.pages

                    PlasmaComponents.Button {
                        required property string modelData

                        Layout.fillWidth: true
                        Layout.preferredWidth: 1   // both columns the same width
                        enabled: !root.busy
                        checkable: true
                        checked: root.showing === modelData
                        icon.name: root.pinned === modelData ? "window-pin" : ""
                        text: root.title(modelData)
                        onClicked: root.send("show " + modelData)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    enabled: !root.busy && root.pinned !== ""
                    icon.name: "media-playlist-repeat"
                    text: i18n("Auto")
                    onClicked: root.send("auto")
                }

                PlasmaComponents.Button {
                    Layout.fillWidth: true
                    enabled: !root.busy && root.pages.length > 0
                    icon.name: "go-next"
                    text: i18n("Next")
                    onClicked: root.send("next")
                }
            }
        }
    }
}
