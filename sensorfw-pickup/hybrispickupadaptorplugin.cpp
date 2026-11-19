#include "hybrispickupadaptorplugin.h"
#include "hybrispickupadaptor.h"
#include "sensormanager.h"
#include "logging.h"

void HybrisPickupAdaptorPlugin::Register(class Loader&)
{
    sensordLogD() << "registering hybrispickupadaptor as proximityadaptor";
    SensorManager& sm = SensorManager::instance();
    sm.registerDeviceAdaptor<HybrisPickupAdaptor>("proximityadaptor");
}
