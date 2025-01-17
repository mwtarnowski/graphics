#Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the opengl rasterizer op."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import six
import tensorflow as tf

from tensorflow_graphics.rendering.opengl import gen_rasterizer_op as rasterizer
from tensorflow_graphics.rendering.opengl import math as glm
from tensorflow_graphics.util import test_case

# Empty vertex shader
test_vertex_shader = """
#version 460
void main() { }
"""

# Geometry shader that projects the vertices of visible triangles onto the image
# plane.
test_geometry_shader = """
#version 460

uniform mat4 view_projection_matrix;

layout(points) in;
layout(triangle_strip, max_vertices=3) out;

out layout(location = 0) vec3 position;
out layout(location = 1) vec3 normal;
out layout(location = 2) vec2 bar_coord;
out layout(location = 3) float tri_id;

in int gl_PrimitiveIDIn;
layout(binding=0) buffer triangular_mesh { float mesh_buffer[]; };

vec3 get_vertex_position(int i) {
  int o = gl_PrimitiveIDIn * 9 + i * 3;
  return vec3(mesh_buffer[o + 0], mesh_buffer[o + 1], mesh_buffer[o + 2]);
}

bool is_back_facing(vec3 v0, vec3 v1, vec3 v2) {
  vec4 tv0 = view_projection_matrix * vec4(v0, 1.0);
  vec4 tv1 = view_projection_matrix * vec4(v1, 1.0);
  vec4 tv2 = view_projection_matrix * vec4(v2, 1.0);
  tv0 /= tv0.w;
  tv1 /= tv1.w;
  tv2 /= tv2.w;
  vec2 a = (tv1.xy - tv0.xy);
  vec2 b = (tv2.xy - tv0.xy);
  return (a.x * b.y - b.x * a.y) <= 0;
}

void main() {
  vec3 v0 = get_vertex_position(0);
  vec3 v1 = get_vertex_position(1);
  vec3 v2 = get_vertex_position(2);

  // Cull back-facing triangles.
  if (is_back_facing(v0, v1, v2)) {
    return;
  }

  normal = normalize(cross(v1 - v0, v2 - v0));

  vec3 positions[3] = {v0, v1, v2};
  for (int i = 0; i < 3; ++i) {
    // gl_Position is a pre-defined size 4 output variable
    gl_Position = view_projection_matrix * vec4(positions[i], 1);
    bar_coord = vec2(i==0 ? 1 : 0, i==1 ? 1 : 0);
    tri_id = gl_PrimitiveIDIn;

    position = positions[i];
    EmitVertex();
  }
  EndPrimitive();
}
"""

# Fragment shader that packs barycentric coordinates, triangle index, and depth
# map in a resulting vec4 per pixel.
test_fragment_shader = """
#version 420

in layout(location = 0) vec3 position;
in layout(location = 1) vec3 normal;
in layout(location = 2) vec2 bar_coord;
in layout(location = 3) float tri_id;

out vec4 output_color;

void main() {
  output_color = vec4(bar_coord, tri_id, position.z);
}
"""


class RasterizerOPTest(test_case.TestCase):

  def test_rasterize(self):
    height = 500
    width = 500
    camera_origin = (0.0, 0.0, 0.0)
    camera_up = (0.0, 1.0, 0.0)
    look_at = (0.0, 0.0, 1.0)
    fov = (60.0 * np.math.pi / 180,)
    near_plane = (1.0,)
    far_plane = (10.0,)

    world_to_camera = glm.look_at_right_handed(camera_origin, look_at,
                                               camera_up)
    perspective_matrix = glm.perspective_right_handed(
        fov, (float(width) / float(height),), near_plane, far_plane)
    view_projection_matrix = tf.matmul(perspective_matrix, world_to_camera)
    view_projection_matrix = tf.squeeze(view_projection_matrix)

    for depth in range(2, 5):
      tris = np.array(
          [[-10.0, 10.0, depth], [10.0, 10.0, depth], [0.0, -10.0, depth]],
          dtype=np.float32)
      tris_tf = tf.reshape(tris, [-1])

      render_parameters = {
          "view_projection_matrix": ("mat", view_projection_matrix),
          "triangular_mesh": ("buffer", tris_tf)
      }

      render_parameters = list(six.iteritems(render_parameters))
      variable_names = [v[0] for v in render_parameters]
      variable_kinds = [v[1][0] for v in render_parameters]
      variable_values = [v[1][1] for v in render_parameters]

      result = rasterizer.rasterize(
          num_points=tris.shape[0],
          variable_names=variable_names,
          variable_kinds=variable_kinds,
          variable_values=variable_values,
          output_resolution=(width, height),
          vertex_shader=test_vertex_shader,
          geometry_shader=test_geometry_shader,
          fragment_shader=test_fragment_shader,
      )

      gt = np.tile((0, depth), (width, height, 1))
      self.assertAllClose(result[..., 2:4], gt)


if __name__ == "__main__":
  test_case.main()
