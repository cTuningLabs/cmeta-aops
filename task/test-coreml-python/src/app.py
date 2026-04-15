import coremltools as ct
import numpy as np

# Create a simple linear model: y = 2x
from coremltools.models import datatypes
from coremltools.models import MLModel
from coremltools.models.neural_network import NeuralNetworkBuilder

# Define input/output
input_features = [("input", datatypes.Array(1))]
output_features = [("output", datatypes.Array(1))]

# Build model
builder = NeuralNetworkBuilder(input_features, output_features)

# Add a single linear layer
builder.add_inner_product(
    name="linear",
    W=np.array([[2.0]]),  # weight
    b=np.array([0.0]),    # bias
    input_channels=1,
    output_channels=1,
    has_bias=True,
    input_name="input",
    output_name="output"
)

# Build model object
model = MLModel(builder.spec)

# Run prediction
result = model.predict({"input": np.array([3.0])})

print(result)
