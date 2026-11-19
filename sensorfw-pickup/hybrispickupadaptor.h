// Pick-up gesture -> "proximity" channel adaptor for sensorfw (Galaxy Tab S7+, Droidian).
// The Wi-Fi tablet has no proximity sensor, so this plugin takes over the "proximityadaptor" slot and
// flips withinProximity on every pick-up event. iio-sensor-proxy (via hadess-sensorfw-proxy) then
// emits a ProximityNear change on D-Bus that a user daemon turns into "wake the screen".
#ifndef HYBRISPICKUPADAPTOR_H
#define HYBRISPICKUPADAPTOR_H
#include "hybrisadaptor.h"
#include "deviceadaptorringbuffer.h"
#include "datatypes/orientationdata.h"
#include <QTimer>

#ifndef SENSOR_TYPE_PICK_UP_GESTURE
#define SENSOR_TYPE_PICK_UP_GESTURE (25)
#endif

class HybrisPickupAdaptor : public HybrisAdaptor
{
    Q_OBJECT
public:
    static DeviceAdaptor* factoryMethod(const QString& id) { return new HybrisPickupAdaptor(id); }
    HybrisPickupAdaptor(const QString& id);
    ~HybrisPickupAdaptor();
    bool startSensor();
    void stopSensor();
    void sendInitialData();
protected:
    void processSample(const sensors_event_t& data);
private:
    DeviceAdaptorRingBuffer<ProximityData>* buffer;
    bool flip;
    void push(bool near);
};
#endif
