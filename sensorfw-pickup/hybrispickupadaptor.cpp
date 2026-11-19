#include "hybrispickupadaptor.h"
#include "logging.h"
#include "datatypes/utils.h"

HybrisPickupAdaptor::HybrisPickupAdaptor(const QString& id) :
    HybrisAdaptor(id, SENSOR_TYPE_PICK_UP_GESTURE), buffer(nullptr), flip(false)
{
    if (isValid()) {
        buffer = new DeviceAdaptorRingBuffer<ProximityData>(1);
        setAdaptedSensor("proximity", "Pick-up gesture (as proximity toggles)", buffer);
        setDescription("Hybris pick-up gesture");
    }
}

HybrisPickupAdaptor::~HybrisPickupAdaptor()
{
    delete buffer;
}

bool HybrisPickupAdaptor::startSensor()
{
    if (!HybrisAdaptor::startSensor())
        return false;
    sensordLogD() << id() << "pickup start";
    return true;
}

void HybrisPickupAdaptor::stopSensor()
{
    HybrisAdaptor::stopSensor();
    sensordLogD() << id() << "pickup stop";
}

void HybrisPickupAdaptor::push(bool near)
{
    if (!buffer)
        return;
    ProximityData *d = buffer->nextSlot();
    d->timestamp_ = Utils::getTimeStamp();
    d->withinProximity_ = near;
    d->value_ = near ? 0 : 5;
    buffer->commit();
    buffer->wakeUpReaders();
}

void HybrisPickupAdaptor::sendInitialData()
{
    push(flip);
}

void HybrisPickupAdaptor::processSample(const sensors_event_t& data)
{
    Q_UNUSED(data);
    flip = !flip;                       // every pick-up toggles the value so listeners always see a change
    sensordLogW() << id() << "pick-up gesture";
    push(flip);
    // one-shot sensor: the HAL disarms it after firing; re-arm shortly after
    QTimer::singleShot(1500, this, [this]() {
        if (isRunning()) { HybrisAdaptor::stopSensor(); HybrisAdaptor::startSensor(); }
    });
}
