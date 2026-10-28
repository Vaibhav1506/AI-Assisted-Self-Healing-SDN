# Dashboard screenshot provenance

## Automatic failback timeline

![Automatic failback timeline](L13_L14_Team5_Failback_Timeline.jpg)

Source recording: [`20261028T031343Z-9deb6c3e`](../runs/failback/20261028T031343Z-9deb6c3e/summary.json).
Six switches, guarded RF, link failure, 4 Mbps application load, 10 Mbps links,
automatic return enabled. This original viewport capture shows the event timeline
and recovery outcome. Its primary-restored event occurs around 33.37 seconds.

## Separate high-load dashboard example

![Dashboard at 10 Mbps offered load](L13_L14_Team5_Dashboard_Stress_10Mbps.png)

Source recording: [`20261027T191045Z-3101b8ae`](../runs/additional/20261027T191045Z-3101b8ae/summary.json).
Six switches, guarded RF, no injected fault, 10 Mbps application load on 10 Mbps
links. High utilization and transient probe loss produced multiple route changes.
This is a stress illustration, not the report's 4 Mbps normal-operation baseline.
The screenshot's selected controls do not change the stored recording.

Both files are original captures from the working dashboard. They have not been
redrawn or used as substitutes for source code or numerical evidence.
